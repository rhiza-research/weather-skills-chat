<script lang="ts">
	import { v4 as uuidv4 } from 'uuid';
	import { toast } from 'svelte-sonner';
	import { PaneGroup, Pane, PaneResizer } from 'paneforge';

	import { getContext, onDestroy, onMount, tick } from 'svelte';
	const i18n: Writable<i18nType> = getContext('i18n');

	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	import { get, type Unsubscriber, type Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import { WEBUI_BASE_URL, WEBUI_API_BASE_URL } from '$lib/constants';

	import {
		chatId,
		chats,
		config,
		type Model,
		models,
		tags as allTags,
		settings,
		showSidebar,
		WEBUI_NAME,
		banners,
		user,
		socket,
		showControls,
		showCallOverlay,
		temporaryChatEnabled,
		mobile,
		showOverview,
		chatTitle,
		showArtifacts,
		tools,
		toolServers,
		activeOrganizationId,
		organizations,
		preferencesReady
	} from '$lib/stores';
	import {
		copyToClipboard,
		getMessageContentParts,
		createMessagesList,
		extractSentencesForAudio,
		splitStream,
		sleep,
		removeDetails,
		getPromptVariables,
		getTimeRange
	} from '$lib/utils';
	import { chatScrollFor, onChatTailRequest, rememberChatScroll } from '$lib/chat/scroll';
	import { convertMessagesToHistory } from '$lib/utils/history';
	import {
		GENERATION_HEARTBEAT_ACTION,
		GENERATION_LOST_MESSAGE,
		clearSpinningToolCalls,
		formatGenerationRequestError
	} from '$lib/utils/generationLiveness';
	import { isUsageLimitMessage } from '$lib/utils/usage';
	import {
		CHAT_CONFLICT_MESSAGE,
		isChatBusy,
		isChatConflict,
		recoverEditConflict,
		recoverSendConflict,
		writeErrorMessage
	} from '$lib/chat/conflict';

	import { generateChatCompletion } from '$lib/apis/ollama';
	import {
		addTagById,
		cloneChatById,
		createNewChat,
		deleteTagById,
		deleteTagsById,
		getAllTags,
		applyChatHistoryPatch,
		getChatById,
		getTagsById
	} from '$lib/apis/chats';
	import {
		beginLive,
		documentForOpen,
		isLive,
		endLive,
		liveMessageIdFor,
		isTranscriptEvent,
		onDocument,
		onOpenTranscript,
		onTurnLost,
		putChat,
		holdHistory,
		holdPendingTurn,
		moveTurnToEnd,
		refetchChat,
		revisionOf,
		settleLoadedTurn,
		setViewingLeaf,
		viewingLeafFor
	} from '$lib/chat/cache';
	import { generateOpenAIChatCompletion } from '$lib/apis/openai';
	import { processWeb, processWebSearch, processYoutubeVideo } from '$lib/apis/retrieval';
	import { createOpenAITextStream } from '$lib/apis/streaming';
	import { getAndUpdateUserLocation, getUserById, getUserSettings } from '$lib/apis/users';
	import {
		generateQueries,
		chatAction,
		generateMoACompletion,
		stopTask,
		getTaskIdsByChatId
	} from '$lib/apis';
	import { getToolSummary } from '$lib/apis/tools';
	import { uploadFile } from '$lib/apis/files';
	import {
		copyFileIntoChatArtifacts,
		fileFromDataUrl
	} from '$lib/apis/artifacts';
	import { defaultEnabledToolIds } from '$lib/utils/toolDisplay';
	import { revealApp } from '$lib/utils/splash';

	import Banner from '../common/Banner.svelte';
	import MessageInput from '$lib/components/chat/MessageInput.svelte';
	import Navbar from '$lib/components/chat/Navbar.svelte';
	import ChatControls from './ChatControls.svelte';
	import EventConfirmDialog from '../common/ConfirmDialog.svelte';
	import Placeholder from './Placeholder.svelte';
	import NotificationToast from '../NotificationToast.svelte';
	import Spinner from '../common/Spinner.svelte';
	import DocumentChartBar from '../icons/DocumentChartBar.svelte';

	export let chatIdProp = '';

	let loading = false;
	let loadingChatId = null; // guards against re-entrant chat loads
	let messagesComponent = null;
	let messagesLoad = null;

	$: if (
		($settings?.landingPageMode === 'chat' ||
			createMessagesList(history, history.currentId).length > 0) &&
		!messagesComponent &&
		!messagesLoad
	) {
		messagesLoad = import('./Messages.svelte').then((module) => {
			messagesComponent = module.default;
		});
	}

	const eventTarget = new EventTarget();
	let controlPane;
	let controlPaneComponent;

	let autoScroll = true;
	let newMessagesBelow = false;
	let heardBelowId = '';
	let processing = '';
	let messagesContainerElement: HTMLDivElement;
	let pinningScroll = false;
	let scrollStopTimer = 0;
	/** Chat id whose transcript is actually on screen. Scroll saves go here, not to a chat that is still loading. */
	let scrollChatId = '';
	/** Re-apply a saved position while the transcript is still growing, until the user scrolls. */
	let settleScroll = false;
	let paintKey = 0;

	let navbarElement;

	let showEventConfirmation = false;
	let eventConfirmationTitle = '';
	let eventConfirmationMessage = '';
	let eventConfirmationInput = false;
	let eventConfirmationInputPlaceholder = '';
	let eventConfirmationInputValue = '';
	let eventCallback = null;

	let chatIdUnsubscriber: Unsubscriber | undefined;
	let artifactsBumpTimer: ReturnType<typeof setTimeout> | null = null;

	let selectedModels = [''];
	let atSelectedModel: Model | undefined;
	let selectedModelIds = [];
	$: selectedModelIds = atSelectedModel !== undefined ? [atSelectedModel.id] : selectedModels;

	let selectedToolIds = [];
	let imageGenerationEnabled = false;
	let webSearchEnabled = false;
	let codeInterpreterEnabled = false;

	let chat = null;
	let tags = [];
	let chatOwnerName = '';
	$: chatWritable =
		!chat || !chat.user_id || !$user?.id || chat.user_id === $user.id || $user?.role === 'admin';

	let history = {
		messages: {},
		currentId: null
	};

	let taskIds = null;
	let stopRequested = false;

	// Chat Input
	let prompt = '';
	let chatFiles = [];
	let files = [];
	let params = {};

	let artifactPanelGeneration = 0;
	let chatAlive = true;
	let stopControlsWatch: Unsubscriber = () => {};

	const openArtifactsPanel = async (forChatId: string | null = null) => {
		const generation = artifactPanelGeneration;
		const stillHere = () =>
			generation === artifactPanelGeneration && (!forChatId || get(chatId) === forChatId);
		if (!stillHere()) return;
		const stored = parseInt(localStorage.chatControlsSize);
		if (!stored || stored < 20 || stored > 45) {
			localStorage.chatControlsSize = '30';
		}
		await showOverview.set(false);
		await showCallOverlay.set(false);
		if (!stillHere()) return;
		await showArtifacts.set(true);
		await showControls.set(true);
		if (!stillHere()) {
			showArtifacts.set(false);
			showControls.set(false);
			return;
		}
		await tick();
		if (!stillHere()) return;
		controlPaneComponent?.openPane?.();
		await tick();
		if (!stillHere()) return;
		controlPaneComponent?.openPane?.();
	};

	let pendingArtifactFiles: File[] = [];

	const copyPendingArtifacts = async (destChatId, fileItems = []) => {
		if (!destChatId || destChatId === 'local' || !pendingArtifactFiles.length) {
			pendingArtifactFiles = [];
			return;
		}
		const byName = new Map(pendingArtifactFiles.map((file) => [file.name, file]));
		for (const item of fileItems) {
			const file =
				item?.sourceFile instanceof File
					? item.sourceFile
					: item?.name
						? byName.get(item.name)
						: null;
			if (!file) continue;
			try {
				const path = await copyFileIntoChatArtifacts(localStorage.token, destChatId, file);
				if (path) item.sandboxPath = path;
			} catch (e) {
				console.error('Failed to copy chat-bar file into artifacts', e);
			}
		}
		// Any leftovers not tied to a message item (still copy by filename).
		for (const file of pendingArtifactFiles) {
			const already = fileItems.some(
				(item) => item?.sandboxPath && (item.name === file.name || item.sandboxPath === file.name)
			);
			if (already) continue;
			try {
				await copyFileIntoChatArtifacts(localStorage.token, destChatId, file);
			} catch (e) {
				console.error('Failed to copy chat-bar file into artifacts', e);
			}
		}
		pendingArtifactFiles = [];
	};

	const loadChatForProp = async (id: string) => {
		if (!id || loadingChatId === id) {
			return;
		}
		loadingChatId = id;
		loading = true;
		stopRequested = false;
		chatId.set(id);
		showOverview.set(false);
		showCallOverlay.set(false);

		prompt = '';
		files = [];
		selectedToolIds = [];
		webSearchEnabled = false;
		imageGenerationEnabled = false;
		codeInterpreterEnabled = false;

		try {
			const ok = await loadChat(id);
			// A newer navigation superseded this load.
			if (loadingChatId !== id) {
				return;
			}
			if (!ok) {
				loading = false;
				loadingChatId = null;
				revealApp();
				await goto('/');
				return;
			}

			loading = false;
			await tick();
			if (chatAlive && get(chatId) === id) await openArtifactsPanel(id);
			revealApp();

			if (localStorage.getItem(`chat-input-${id}`)) {
				try {
					const input = JSON.parse(localStorage.getItem(`chat-input-${id}`));
					prompt = input.prompt;
					files = input.files;
					selectedToolIds = input.selectedToolIds;
					webSearchEnabled = input.webSearchEnabled;
					imageGenerationEnabled = input.imageGenerationEnabled;
					codeInterpreterEnabled = input.codeInterpreterEnabled;
				} catch (e) {}
			}

			document.getElementById('chat-input')?.focus();
		} catch (e) {
			console.error(e);
			if (loadingChatId === id) {
				loading = false;
				loadingChatId = null;
			}
			revealApp();
		}
	};

	$: if (chatIdProp) {
		loadChatForProp(chatIdProp);
	} else {
		loadingChatId = null;
	}

	$: if (selectedModels && chatIdProp !== '') {
		saveSessionSelectedModels();
	}

	const saveSessionSelectedModels = () => {
		if (selectedModels.length === 0 || (selectedModels.length === 1 && selectedModels[0] === '')) {
			return;
		}
		sessionStorage.selectedModels = JSON.stringify(selectedModels);
		console.log('saveSessionSelectedModels', selectedModels, sessionStorage.selectedModels);
	};

	let toolsLoad = null;

	$: if (atSelectedModel || selectedModels.some((id) => id)) {
		setToolIds();
	}

	const setToolIds = async () => {
		if (!$tools) {
			if (!toolsLoad) {
				toolsLoad = getToolSummary(localStorage.token).finally(() => {
					toolsLoad = null;
				});
			}
			tools.set(await toolsLoad);
		}

		if (selectedModels.length !== 1 && !atSelectedModel) {
			return;
		}

		const model = atSelectedModel ?? $models.find((m) => m.id === selectedModels[0]);
		if (model) {
			// Enable org-usable tools/skills by default (highest skill version).
			// Catalog "enabled by default" only seeds the workspace toggle; the
			// tools list already reflects org-admin enablement.
			selectedToolIds = defaultEnabledToolIds($tools ?? []);
		}
	};

	const showMessage = async (message) => {
		const _chatId = JSON.parse(JSON.stringify($chatId));
		let _messageId = JSON.parse(JSON.stringify(message.id));

		let messageChildrenIds = [];
		if (_messageId === null) {
			messageChildrenIds = Object.keys(history.messages).filter(
				(id) => history.messages[id].parentId === null
			);
		} else {
			messageChildrenIds = history.messages[_messageId].childrenIds;
		}

		while (messageChildrenIds.length !== 0) {
			_messageId = messageChildrenIds.at(-1);
			messageChildrenIds = history.messages[_messageId].childrenIds;
		}

		history.currentId = _messageId;

		await tick();
		await tick();
		await tick();

		const messageElement = document.getElementById(`message-${message.id}`);
		if (messageElement) {
			messageElement.scrollIntoView({ behavior: 'smooth' });
		}

		await tick();
		if (_chatId) setViewingLeaf(_chatId, history.currentId);
	};

	const mergeRemotePreservingLive = (remoteMessages, liveChat: string) => {
		if (!remoteMessages) return;
		const keep = liveMessageIdFor(liveChat);
		for (const [messageId, remote] of Object.entries(remoteMessages)) {
			if (messageId !== keep) {
				history.messages[messageId] = remote;
				continue;
			}
			const local = history.messages[messageId];
			// The server copy is the finished turn. Keeping an empty local
			// message here drops the reply and the liveness poll then calls it
			// a lost connection.
			if (!local || remote?.done === true) history.messages[messageId] = remote;
		}
	};

	const chatEventHandler = async (event, cb) => {
		console.log(event);

		const type = event?.data?.type ?? null;
		if (
			type === 'execute:python' ||
			type === 'execute:tool' ||
			type === 'request:chat:completion'
		) {
			return;
		}

		if (event.chat_id !== $chatId) return;
		// Transcript text is written once, in the cache. Painting happens in
		// onOpenTranscript so this handler cannot append the same tokens again.
		if (isTranscriptEvent(type)) return;

		await tick();
		const data = event?.data?.data ?? null;

		if (type === 'chat:title') {
			const title = typeof data === 'string' ? data : data?.title;
			if (title) chatTitle.set(title);
			if (title && event.chat_id) {
				chats.update((list) =>
					(list ?? []).map((item) => (item.id === event.chat_id ? { ...item, title } : item))
				);
			}
		} else if (type === 'chat:tags') {
			chat = await getChatById(localStorage.token, $chatId);
			allTags.set(await getAllTags(localStorage.token));
		} else if (type === 'notification') {
			const toastType = data?.type ?? 'info';
			const toastContent = data?.content ?? '';

			if (toastType === 'success') {
				toast.success(toastContent);
			} else if (toastType === 'error') {
				toast.error(toastContent);
			} else if (toastType === 'warning') {
				toast.warning(toastContent);
			} else {
				toast.info(toastContent);
			}
		} else if (type === 'confirmation') {
			eventCallback = cb;

			eventConfirmationInput = false;
			showEventConfirmation = true;

			eventConfirmationTitle = data.title;
			eventConfirmationMessage = data.message;
		} else if (type === 'execute') {
			eventCallback = cb;

			try {
				const asyncFunction = new Function(`return (async () => { ${data.code} })()`);
				const result = await asyncFunction();

				if (cb) {
					cb(result);
				}
			} catch (error) {
				console.error('Error executing code:', error);
			}
		} else if (type === 'input') {
			eventCallback = cb;

			eventConfirmationInput = true;
			showEventConfirmation = true;

			eventConfirmationTitle = data.title;
			eventConfirmationMessage = data.message;
			eventConfirmationInputPlaceholder = data.placeholder;
			eventConfirmationInputValue = data?.value ?? '';
		} else {
			console.log('Unknown message type', data);
		}
	};

	const onMessageHandler = async (event: {
		origin: string;
		data: { type: string; text: string };
	}) => {
		if (event.origin !== window.origin) {
			return;
		}

		// Replace with your iframe's origin
		if (event.data.type === 'input:prompt') {
			console.debug(event.data.text);

			const inputElement = document.getElementById('chat-input');

			if (inputElement) {
				prompt = event.data.text;
				inputElement.focus();
			}
		}

		if (event.data.type === 'action:submit') {
			console.debug(event.data.text);

			if (prompt !== '') {
				await tick();
				submitPrompt(prompt);
			}
		}

		if (event.data.type === 'input:prompt:submit') {
			console.debug(event.data.text);

			if (event.data.text !== '') {
				await tick();
				submitPrompt(event.data.text);
			}
		}
	};

	let stopDocumentWatch = () => {};
	let stopLostWatch = () => {};
	let stopPaint = () => {};
	let stopTailRequest = () => {};

	onMount(async () => {
		console.log('mounted');
		stopLostWatch = onTurnLost((id) => {
			if (id === get(chatId)) toast.error(GENERATION_LOST_MESSAGE);
		});
		stopDocumentWatch = onDocument((id, document) => {
			if (!document || id !== get(chatId)) return;
			const heldTop = autoScroll ? null : messagesContainerElement?.scrollTop ?? 0;
			// Opening a chat fetches it into the cache and notifies here. That is
			// not a new response — settleScroll is still true — so do not mark
			// unseen or play a sound.
			if (!autoScroll && !settleScroll) {
				noteNewMessagesBelow(document?.chat?.history?.currentId || '');
			}
			if (document?.chat?.history && document.chat.history === history) {
				// ResponseMessage keeps a clone and only refreshes when the
				// messages object itself is replaced.
				const next = { ...history, messages: { ...history.messages } };
				document.chat.history = next;
				history = next;
				paintKey += 1;
				if (settleScroll) placeChatScroll(id);
				else if (heldTop != null) restoreReadingPosition(heldTop);
				else if (autoScroll) pinScrollToEnd();
				return;
			}
			if (isLive(id)) {
				const remoteMessages = document?.chat?.history?.messages;
				if (!remoteMessages) return;
				mergeRemotePreservingLive(remoteMessages, id);
				history = history;
				if (settleScroll) placeChatScroll(id);
				else if (heldTop != null) restoreReadingPosition(heldTop);
				return;
			}
			applyChatDocument(document);
			history = history;
			if (settleScroll) placeChatScroll(id);
			else if (heldTop != null) restoreReadingPosition(heldTop);
			else if (autoScroll) pinScrollToEnd();
		});
		stopPaint = onOpenTranscript((event) => paintTranscript(event));
		window.addEventListener('message', onMessageHandler);
		$socket?.on('chat-events', chatEventHandler);
		stopTailRequest = onChatTailRequest((id) => {
			if (id !== get(chatId)) return;
			heardBelowId = '';
			scrollToBottom();
		});

		if (!$chatId) {
			chatIdUnsubscriber = chatId.subscribe(async (value) => {
				if (!value) {
					await tick(); // Wait for DOM updates
					if (!chatAlive || get(chatId) || leftNewChatScreen()) return;
					await initNewChat();
				}
			});
		} else {
			if ($temporaryChatEnabled) {
				await goto('/');
			}
		}

		if (localStorage.getItem(`chat-input-${chatIdProp}`)) {
			try {
				const input = JSON.parse(localStorage.getItem(`chat-input-${chatIdProp}`));
				prompt = input.prompt;
				files = input.files;
				selectedToolIds = input.selectedToolIds;
				webSearchEnabled = input.webSearchEnabled;
				imageGenerationEnabled = input.imageGenerationEnabled;
				codeInterpreterEnabled = input.codeInterpreterEnabled;
			} catch (e) {
				prompt = '';
				files = [];
				selectedToolIds = [];
				webSearchEnabled = false;
				imageGenerationEnabled = false;
				codeInterpreterEnabled = false;
			}
		}

		// The store calls this immediately with the current value. That first
		// "closed" notice is async, so it can land after a later open and
		// wipe the artifacts flag while leaving the pane expanded.
		stopControlsWatch = showControls.subscribe(async (value) => {
			await tick();
			if (!chatAlive || get(showControls) !== value) return;
			const panelShown =
				get(showArtifacts) || get(showOverview) || get(showCallOverlay);
			if (controlPane && controlPaneComponent && !$mobile) {
				try {
					if (value && panelShown) {
						controlPaneComponent.openPane();
						await tick();
						if (!chatAlive || !get(showControls)) return;
						controlPaneComponent.openPane();
					} else if (!value) {
						controlPane.collapse();
					}
				} catch (e) {
					// ignore
				}
			}

			if (!value && !get(showControls)) {
				if (!chatAlive || leftNewChatScreen()) return;
				showCallOverlay.set(false);
				showOverview.set(false);
				showArtifacts.set(false);
			}
		});

		const chatInput = document.getElementById('chat-input');
		chatInput?.focus();

		chats.subscribe(() => {});
	});

	onDestroy(() => {
		chatAlive = false;
		if (scrollChatId) saveChatScroll(scrollChatId);
		stopDocumentWatch();
		stopLostWatch();
		stopPaint();
		stopTailRequest();
		stopControlsWatch();
		chatIdUnsubscriber?.();
		if (artifactsBumpTimer) clearTimeout(artifactsBumpTimer);
		window.removeEventListener('message', onMessageHandler);
		window.clearTimeout(scrollStopTimer);
		cancelAnimationFrame(tailWatch);
		$socket?.off('chat-events', chatEventHandler);
	});

	// File upload functions

	const uploadGoogleDriveFile = async (fileData) => {
		console.log('Starting uploadGoogleDriveFile with:', {
			id: fileData.id,
			name: fileData.name,
			url: fileData.url,
			headers: {
				Authorization: `Bearer ${token}`
			}
		});

		// Validate input
		if (!fileData?.id || !fileData?.name || !fileData?.url || !fileData?.headers?.Authorization) {
			throw new Error('Invalid file data provided');
		}

		const tempItemId = uuidv4();
		const fileItem = {
			type: 'file',
			file: '',
			id: null,
			url: fileData.url,
			name: fileData.name,
			collection_name: '',
			status: 'uploading',
			error: '',
			itemId: tempItemId,
			size: 0
		};

		try {
			files = [...files, fileItem];
			console.log('Processing web file with URL:', fileData.url);

			// Configure fetch options with proper headers
			const fetchOptions = {
				headers: {
					Authorization: fileData.headers.Authorization,
					Accept: '*/*'
				},
				method: 'GET'
			};

			// Attempt to fetch the file
			console.log('Fetching file content from Google Drive...');
			const fileResponse = await fetch(fileData.url, fetchOptions);

			if (!fileResponse.ok) {
				const errorText = await fileResponse.text();
				throw new Error(`Failed to fetch file (${fileResponse.status}): ${errorText}`);
			}

			// Get content type from response
			const contentType = fileResponse.headers.get('content-type') || 'application/octet-stream';
			console.log('Response received with content-type:', contentType);

			// Convert response to blob
			console.log('Converting response to blob...');
			const fileBlob = await fileResponse.blob();

			if (fileBlob.size === 0) {
				throw new Error('Retrieved file is empty');
			}

			console.log('Blob created:', {
				size: fileBlob.size,
				type: fileBlob.type || contentType
			});

			// Create File object with proper MIME type
			const file = new File([fileBlob], fileData.name, {
				type: fileBlob.type || contentType
			});

			console.log('File object created:', {
				name: file.name,
				size: file.size,
				type: file.type
			});

			if (file.size === 0) {
				throw new Error('Created file is empty');
			}

			// Upload file to server
			console.log('Uploading file to server...');
			const uploadedFile = await uploadFile(localStorage.token, file);

			if (!uploadedFile) {
				throw new Error('Server returned null response for file upload');
			}

			console.log('File uploaded successfully:', uploadedFile);

			fileItem.status = 'uploaded';
			fileItem.file = uploadedFile;
			fileItem.id = uploadedFile.id;
			fileItem.size = file.size;
			fileItem.collection_name = uploadedFile?.meta?.collection_name;
			fileItem.url = `${WEBUI_API_BASE_URL}/files/${uploadedFile.id}`;
			fileItem.sourceFile = file;
			try {
				fileItem.sandboxPath = await copyFileIntoChatArtifacts(
					localStorage.token,
					$chatId,
					file
				);
				void fileItem.sandboxPath;
			} catch (e) {
				console.error('Failed to copy chat-bar file into artifacts', e);
			}

			files = files;
			toast.success($i18n.t('File uploaded successfully'));
		} catch (e) {
			console.error('Error uploading file:', e);
			files = files.filter((f) => f.itemId !== tempItemId);
			toast.error(
				$i18n.t('Error uploading file: {{error}}', {
					error: e.message || 'Unknown error'
				})
			);
		}
	};

	const uploadWeb = async (url) => {
		console.log(url);

		const fileItem = {
			type: 'doc',
			name: url,
			collection_name: '',
			status: 'uploading',
			url: url,
			error: ''
		};

		try {
			files = [...files, fileItem];
			const res = await processWeb(localStorage.token, '', url);

			if (res) {
				fileItem.status = 'uploaded';
				fileItem.collection_name = res.collection_name;
				fileItem.file = {
					...res.file,
					...fileItem.file
				};

				files = files;
			}
		} catch (e) {
			// Remove the failed doc from the files array
			files = files.filter((f) => f.name !== url);
			toast.error(JSON.stringify(e));
		}
	};

	const uploadYoutubeTranscription = async (url) => {
		console.log(url);

		const fileItem = {
			type: 'doc',
			name: url,
			collection_name: '',
			status: 'uploading',
			context: 'full',
			url: url,
			error: ''
		};

		try {
			files = [...files, fileItem];
			const res = await processYoutubeVideo(localStorage.token, url);

			if (res) {
				fileItem.status = 'uploaded';
				fileItem.collection_name = res.collection_name;
				fileItem.file = {
					...res.file,
					...fileItem.file
				};
				files = files;
			}
		} catch (e) {
			// Remove the failed doc from the files array
			files = files.filter((f) => f.name !== url);
			toast.error(`${e}`);
		}
	};

	//////////////////////////
	// Web functions
	//////////////////////////

	const applyStartupModel = () => {
		if ($chatId) return;
		if (selectedModels.some((id) => id && $models.some((model) => model.id === id))) return;
		const orgId = get(activeOrganizationId) || $user?.id;
		const orgDefaultModels = orgId
			? ($organizations.find((org) => org.id === orgId)?.default_models || '')
					.split(',')
					.map((id) => id.trim())
					.filter(Boolean)
			: [];
		let next = [];
		if (orgDefaultModels.length) {
			next = orgDefaultModels;
		} else if ($settings?.models) {
			next = $settings.models;
		} else if ($config?.default_models) {
			next = $config.default_models.split(',');
		}
		next = next.filter((id) => $models.some((model) => model.id === id));
		if (!next.length && $models[0]) {
			next = [$models[0].id];
		}
		if (next.length) {
			selectedModels = next;
		}
	};

	$: if (
		$preferencesReady &&
		$models.length > 0 &&
		!selectedModels.some((id) => id && $models.some((model) => model.id === id))
	) {
		applyStartupModel();
	}

	// The new-chat screen and a chat page are different component instances
	// that share the panel stores. Once navigation has left "/", this instance
	// must not clear the chat id or close the panel the next page just opened.
	const leftNewChatScreen = () => !chatIdProp && get(page).url.pathname.includes('/c/');

	const initNewChat = async () => {
		if (!chatAlive || leftNewChatScreen()) return;
		if ($page.url.searchParams.get('models')) {
			selectedModels = $page.url.searchParams.get('models')?.split(',');
		} else if ($page.url.searchParams.get('model')) {
			const urlModels = $page.url.searchParams.get('model')?.split(',');

			if (urlModels.length === 1) {
				const m = $models.find((m) => m.id === urlModels[0]);
				if (!m) {
					const modelSelectorButton = document.getElementById('model-selector-0-button');
					if (modelSelectorButton) {
						modelSelectorButton.click();
						await tick();

						const modelSelectorInput = document.getElementById('model-search-input');
						if (modelSelectorInput) {
							modelSelectorInput.focus();
							modelSelectorInput.value = urlModels[0];
							modelSelectorInput.dispatchEvent(new Event('input'));
						}
					}
				} else {
					selectedModels = urlModels;
				}
			} else {
				selectedModels = urlModels;
			}
		} else {
			const orgId = get(activeOrganizationId) || $user?.id;
			const orgDefaultModels = orgId
				? ($organizations.find((t) => t.id === orgId)?.default_models || '')
						.split(',')
						.map((s) => s.trim())
						.filter(Boolean)
				: [];

			if (orgDefaultModels.length) {
				selectedModels = orgDefaultModels;
				sessionStorage.removeItem('selectedModels');
			} else if (sessionStorage.selectedModels) {
				selectedModels = JSON.parse(sessionStorage.selectedModels);
				sessionStorage.removeItem('selectedModels');
			} else {
				if ($settings?.models) {
					selectedModels = $settings?.models;
				} else if ($config?.default_models) {
					console.log($config?.default_models.split(',') ?? '');
					selectedModels = $config?.default_models.split(',');
				}
			}
		}

		if ($models.length > 0) {
			selectedModels = selectedModels.filter((modelId) =>
				$models.some((model) => model.id === modelId)
			);
			if (selectedModels.length === 0 || (selectedModels.length === 1 && selectedModels[0] === '')) {
				selectedModels = [$models[0].id];
			}
		}

		await showCallOverlay.set(false);
		await showOverview.set(false);
		if (!chatAlive || leftNewChatScreen()) return;

		if ($page.url.pathname.includes('/c/')) {
			window.history.replaceState(history.state, '', `/`);
		}

		if (scrollChatId) saveChatScroll(scrollChatId);
		scrollChatId = '';
		autoScroll = true;
		newMessagesBelow = false;
		heardBelowId = '';

		if (!chatAlive || leftNewChatScreen()) return;
		await chatId.set('');
		if (!chatAlive || leftNewChatScreen()) return;
		await chatTitle.set('');
		if (!chatAlive || leftNewChatScreen()) return;
		artifactPanelGeneration += 1;
		await showArtifacts.set(false);
		await showControls.set(false);
		if (!chatAlive || leftNewChatScreen()) return;

		history = {
			messages: {},
			currentId: null
		};

		chatFiles = [];
		params = {};

		if ($page.url.searchParams.get('youtube')) {
			uploadYoutubeTranscription(
				`https://www.youtube.com/watch?v=${$page.url.searchParams.get('youtube')}`
			);
		}
		if ($page.url.searchParams.get('web-search') === 'true') {
			webSearchEnabled = true;
		}

		if ($page.url.searchParams.get('image-generation') === 'true') {
			imageGenerationEnabled = true;
		}

		if ($page.url.searchParams.get('tools')) {
			selectedToolIds = $page.url.searchParams
				.get('tools')
				?.split(',')
				.map((id) => id.trim())
				.filter((id) => id);
		} else if ($page.url.searchParams.get('tool-ids')) {
			selectedToolIds = $page.url.searchParams
				.get('tool-ids')
				?.split(',')
				.map((id) => id.trim())
				.filter((id) => id);
		}

		if ($page.url.searchParams.get('call') === 'true') {
			showCallOverlay.set(true);
			showControls.set(true);
		}

		if ($page.url.searchParams.get('q')) {
			prompt = $page.url.searchParams.get('q') ?? '';

			if (prompt) {
				await tick();
				submitPrompt(prompt);
			}
		}

		if ($models.length > 0) {
			selectedModels = selectedModels.map((modelId) =>
				$models.some((model) => model.id === modelId) ? modelId : ''
			);
			if (!selectedModels.some((modelId) => modelId)) {
				applyStartupModel();
			}
		}

		const chatInput = document.getElementById('chat-input');
		setTimeout(() => chatInput?.focus(), 0);
		revealApp();
	};

	const applyChatDocument = (loadedChat) => {
		const stored = putChat(loadedChat, null)?.document ?? loadedChat;
		chat = stored;
		const chatContent = stored.chat;
		if (!chatContent) return false;
		selectedModels =
			(chatContent?.models ?? undefined) !== undefined
				? chatContent.models
				: [chatContent.models ?? ''];
		if (!chatContent.history) {
			chatContent.history = convertMessagesToHistory(chatContent.messages);
		}
		history = chatContent.history;
		chatTitle.set(chatContent.title);
		params = {};
		chatFiles = chatContent?.files ?? [];
		const incomingId = history.currentId;
		const leaf = viewingLeafFor(stored.id);
		if (leaf && leaf !== incomingId && history?.messages?.[leaf]) {
			if (!incomingId || !messageDescendsFrom(history, incomingId, leaf)) {
				history.currentId = leaf;
			} else {
				setViewingLeaf(stored.id, incomingId);
			}
		}
		return true;
	};

	const messageDescendsFrom = (tree, messageId: string, ancestorId: string) => {
		let cursor = tree?.messages?.[messageId];
		const seen = new Set<string>();
		while (cursor && !seen.has(cursor.id)) {
			if (cursor.id === ancestorId) return true;
			seen.add(cursor.id);
			cursor = cursor.parentId ? tree.messages[cursor.parentId] : null;
		}
		return false;
	};

	const loadChat = async (id: string) => {
		if (scrollChatId && scrollChatId !== id) saveChatScroll(scrollChatId);
		scrollChatId = '';
		autoScroll = false;
		newMessagesBelow = false;
		heardBelowId = '';
		settleScroll = true;
		taskIds = null;
		stopRequested = false;
		chatId.set(id);

		const token = localStorage.token;
		const tagsPromise = getTagsById(token, id).catch(() => []);
		const settingsPromise = getUserSettings(token);
		const tasksPromise = getTaskIdsByChatId(token, id).catch(() => null);

		let loadedChat = null;
		try {
			loadedChat = (await documentForOpen(token, id)).document;
		} catch (error) {
			if (loadingChatId === id) {
				await goto('/');
			}
			return null;
		}
		if (loadingChatId !== id || !loadedChat) {
			if (loadingChatId === id && !loadedChat) await goto('/');
			return null;
		}
		if (!applyChatDocument(loadedChat)) return null;
		loading = false;
		if (messagesLoad) await messagesLoad;
		await tick();
		scrollChatId = id;
		placeChatScroll(id);

		const currentUser = get(user);
		const listed = (get(chats) ?? []).find((item) => item?.id === id);
		const ownerPromise: Promise<string> =
			loadedChat.user_id && loadedChat.user_id !== currentUser?.id
				? listed?.owner_name
					? Promise.resolve(listed.owner_name)
					: getUserById(token, loadedChat.user_id)
							.then((owner) => owner?.name ?? '')
							.catch(() => '')
				: Promise.resolve(currentUser?.name ?? '');

		const [loadedTags, userSettings, taskRes, ownerName] = await Promise.all([
			tagsPromise,
			settingsPromise,
			tasksPromise,
			ownerPromise
		]);
		if (loadingChatId !== id) {
			return null;
		}

		chatOwnerName = ownerName;
		tags = loadedTags ?? [];

		if (userSettings) {
			await settings.set(userSettings.ui);
		} else {
			await settings.set(JSON.parse(localStorage.getItem('settings') ?? '{}'));
		}

		await tick();
		if (settleScroll && get(chatId) === id) placeChatScroll(id);

		taskIds = taskRes?.task_ids?.length ? taskRes.task_ids : null;
		const hasLiveTask = !!(taskIds && taskIds.length);
		await settleLoadedTurn(id, token, hasLiveTask);
		history = history;

		await tick();
		if (settleScroll && get(chatId) === id) placeChatScroll(id);

		return true;
	};

	const messageNode = (id: string) => {
		const node = document.getElementById(`message-${id}`);
		return node instanceof HTMLElement ? node : null;
	};

	/** Lowest message still on screen. */
	const bottomMessageId = (container: HTMLElement) => {
		const viewTop = container.getBoundingClientRect().top;
		const viewBottom = container.getBoundingClientRect().bottom;
		let found = '';
		for (const node of container.querySelectorAll<HTMLElement>('[id^="message-"]')) {
			const id = node.id.slice('message-'.length);
			if (id.startsWith('edit-') || id.startsWith('index-input-') || id.startsWith('feedback-')) {
				continue;
			}
			const rect = node.getBoundingClientRect();
			if (rect.bottom <= viewTop) continue;
			if (rect.top >= viewBottom) break;
			found = id;
		}
		return found;
	};

	/** Line inside the message whose top is closest to the top of the pane. */
	const readingAnchor = (container: HTMLElement, message: HTMLElement) => {
		const line = container.getBoundingClientRect().top;
		let best: HTMLElement | null = null;
		let bestDistance = Infinity;
		for (const node of message.querySelectorAll<HTMLElement>(
			'p, li, pre, img, blockquote, h1, h2, h3, h4, h5, h6'
		)) {
			const distance = Math.abs(node.getBoundingClientRect().top - line);
			if (distance < bestDistance) {
				bestDistance = distance;
				best = node;
			}
		}
		if (!best) return null;
		const image = best instanceof HTMLImageElement ? best : best.querySelector('img');
		if (image instanceof HTMLImageElement && image.alt) {
			const copies = [...message.querySelectorAll('img')].filter((img) => img.alt === image.alt);
			return {
				kind: 'img' as const,
				key: image.alt,
				index: Math.max(copies.indexOf(image), 0),
				offset: image.getBoundingClientRect().top - line
			};
		}
		const text = (best.textContent || '').trim().slice(0, 80);
		if (!text) return null;
		return { kind: 'text' as const, key: text, index: 0, offset: best.getBoundingClientRect().top - line };
	};

	const anchorNode = (message: HTMLElement, kind?: string, key?: string, index = 0) => {
		if (!key) return null;
		if (kind === 'img') {
			const copies = [...message.querySelectorAll<HTMLElement>('img')].filter(
				(img) => img.getAttribute('alt') === key
			);
			return copies[index] ?? null;
		}
		const walker = document.createTreeWalker(message, NodeFilter.SHOW_TEXT);
		let current: Node | null;
		while ((current = walker.nextNode())) {
			if (!current.textContent?.includes(key)) continue;
			const parent = current.parentElement;
			return parent instanceof HTMLElement ? parent : null;
		}
		return null;
	};

	/** Put the saved line back at the same offset inside the pane. */
	const showSavedMessage = (
		container: HTMLElement,
		messageId?: string,
		messageOffset?: number,
		anchorKind?: string,
		anchorKey?: string,
		anchorOffset?: number,
		anchorIndex?: number
	) => {
		const node = messageId ? messageNode(messageId) : null;
		if (!node) return false;
		const anchor = anchorNode(node, anchorKind, anchorKey, anchorIndex ?? 0);
		const target = anchor ?? node;
		const top = target.getBoundingClientRect().top - container.getBoundingClientRect().top;
		const saved = anchor && typeof anchorOffset === 'number' ? anchorOffset : messageOffset;
		const delta =
			typeof saved === 'number'
				? top - saved
				: node.getBoundingClientRect().bottom - container.getBoundingClientRect().bottom;
		if (Math.abs(delta) < 2) return true;
		holdScrollPin();
		container.scrollTop += delta;
		return true;
	};

	let pinCount = 0;
	let tailWatch = 0;
	const holdScrollPin = () => {
		const element = messagesContainerElement;
		pinCount += 1;
		pinningScroll = true;
		let done = false;
		const release = () => {
			if (done) return;
			done = true;
			element?.removeEventListener('scroll', release);
			pinCount = Math.max(0, pinCount - 1);
			pinningScroll = pinCount > 0;
		};
		element?.addEventListener('scroll', release);
		requestAnimationFrame(() => requestAnimationFrame(release));
	};

	/** Reader was at the tail, and this scroll is the pane changing size under them. */
	const tailHeld = (element: HTMLElement, saved: { top: number; atBottom: boolean } | null) => {
		if (!saved?.atBottom) return false;
		const atBottom = element.scrollHeight - element.scrollTop <= element.clientHeight + 5;
		if (atBottom) return false;
		const heightChanged =
			Math.abs(element.scrollHeight - element.clientHeight - saved.top) >= 2;
		const userMovedUp = element.scrollTop < saved.top - 2 && !heightChanged;
		return !userMovedUp;
	};

	const captureScroll = (id: string, element: HTMLElement) => {
		const atBottom = element.scrollHeight - element.scrollTop <= element.clientHeight + 5;
		const saved = chatScrollFor(id);
		// A resize (the sidebar, or images gaining height) moves the pane
		// without the reader scrolling. Keep the tail, or the line they placed.
		if (tailHeld(element, saved)) {
			autoScroll = true;
			pinScrollToEnd();
			return;
		}
		if (
			saved?.anchorKey &&
			!saved.atBottom &&
			!atBottom &&
			Math.abs(element.scrollTop - saved.top) < 2
		) {
			return;
		}
		const messageId = atBottom ? undefined : bottomMessageId(element);
		const node = messageId ? messageNode(messageId) : null;
		const anchor = node ? readingAnchor(element, node) : null;
		rememberChatScroll(id, {
			top: element.scrollTop,
			atBottom,
			messagesCount: saved?.messagesCount ?? 20,
			unseen: !atBottom && (newMessagesBelow || !!saved?.unseen),
			messageId,
			messageOffset: node
				? node.getBoundingClientRect().top - element.getBoundingClientRect().top
				: undefined,
			anchorKind: anchor?.kind,
			anchorKey: anchor?.key,
			anchorIndex: anchor?.index,
			anchorOffset: anchor?.offset
		});
	};

	const saveChatScroll = (id: string) => {
		window.clearTimeout(scrollStopTimer);
		const element = messagesContainerElement;
		if (!id || !element) return;
		captureScroll(id, element);
	};

	const placeSavedScroll = (element: HTMLElement) => {
		if (!scrollChatId) return;
		const saved = chatScrollFor(scrollChatId);
		const atBottom = !saved || saved.atBottom;
		if (settleScroll) autoScroll = atBottom;
		if (atBottom && autoScroll) {
			pinScrollToEnd();
			return;
		}
		if (saved?.messageId) {
			showSavedMessage(
				element,
				saved.messageId,
				saved.messageOffset,
				saved.anchorKind,
				saved.anchorKey,
				saved.anchorOffset,
				saved.anchorIndex
			);
		}
	};

	const placeChatScroll = (id: string) => {
		const element = messagesContainerElement;
		if (!element || get(chatId) !== id) return;
		const saved = chatScrollFor(id);
		const atBottom = !saved || saved.atBottom;
		autoScroll = atBottom;
		if (!atBottom && saved?.unseen) {
			newMessagesBelow = true;
			if (history?.currentId) heardBelowId = history.currentId;
		}
		placeSavedScroll(element);
		if (autoScroll) watchSettledTail();
	};

	/** Follow the latest line while images finish laying out, without waiting on chat metadata. */
	const watchSettledTail = () => {
		cancelAnimationFrame(tailWatch);
		let lastHeight = -1;
		let stable = 0;
		const step = () => {
			tailWatch = 0;
			const element = messagesContainerElement;
			if (!element || !settleScroll || !autoScroll || !scrollChatId) return;
			const saved = chatScrollFor(scrollChatId);
			if (saved && !saved.atBottom) return;
			const pending = [...element.querySelectorAll('img')].some((img) => !img.complete);
			if (element.scrollHeight - element.scrollTop - element.clientHeight > 5) {
				pinScrollToEnd();
			}
			if (element.scrollHeight === lastHeight && !pending) stable += 1;
			else stable = 0;
			lastHeight = element.scrollHeight;
			if (stable < 3) tailWatch = requestAnimationFrame(step);
		};
		tailWatch = requestAnimationFrame(step);
	};

	const restoreReadingPosition = (top: number) => {
		const element = messagesContainerElement;
		if (!element || autoScroll) return;
		const apply = () => {
			if (!messagesContainerElement || autoScroll) return;
			holdScrollPin();
			messagesContainerElement.scrollTop = top;
		};
		void tick().then(apply);
	};

	const pinScrollToEnd = () => {
		const element = messagesContainerElement;
		if (!element || !autoScroll) return;
		const id = scrollChatId;
		const saved = id ? chatScrollFor(id) : null;
		if (settleScroll && saved && !saved.atBottom) return;
		holdScrollPin();
		element.scrollTop = element.scrollHeight;
		if (id) {
			const previous = chatScrollFor(id);
			rememberChatScroll(id, {
				top: element.scrollTop,
				atBottom: true,
				messagesCount: previous?.messagesCount ?? 20,
				unseen: false
			});
		}
	};

	// Keep the tail in view while a reply is streaming and this chat is
	// scrolled to the end. A saved offset is reapplied until the reader scrolls,
	// so a message that grows after open (images) lands on the same line.
	const stickToEnd = (node: HTMLElement) => {
		let frame = 0;
		const schedule = () => {
			cancelAnimationFrame(frame);
			frame = requestAnimationFrame(() => {
				if (pinningScroll) {
					schedule();
					return;
				}
				if (autoScroll && !newMessagesBelow) pinScrollToEnd();
				else if (settleScroll) placeSavedScroll(node);
			});
		};
		const content = node.firstElementChild;
		const observer = new ResizeObserver(() => schedule());
		if (content) observer.observe(content);
		observer.observe(node);
		schedule();
		return {
			destroy() {
				cancelAnimationFrame(frame);
				observer.disconnect();
			}
		};
	};

	const noteNewMessagesBelow = (messageId = '') => {
		if (autoScroll || settleScroll) return;
		newMessagesBelow = true;
		if (scrollChatId) {
			const saved = chatScrollFor(scrollChatId);
			if (saved) rememberChatScroll(scrollChatId, { ...saved, unseen: true });
		}
		if (!messageId || messageId === heardBelowId) return;
		heardBelowId = messageId;
	};

	const scrollToBottom = async () => {
		autoScroll = true;
		newMessagesBelow = false;
		await tick();
		const element = messagesContainerElement;
		if (!element) return;
		holdScrollPin();
		element.scrollTop = element.scrollHeight;
		if (scrollChatId) {
			const saved = chatScrollFor(scrollChatId);
			rememberChatScroll(scrollChatId, {
				top: element.scrollTop,
				atBottom: true,
				messagesCount: saved?.messagesCount ?? 20,
				unseen: false
			});
		}
	};
	const chatCompletedHandler = async (_chatId, _modelId, responseMessageId, _messages) => {
		taskIds = null;
		endLive(responseMessageId);
	};

	const chatActionHandler = async (chatId, actionId, modelId, responseMessageId, event = null) => {
		const messages = createMessagesList(history, responseMessageId);

		const res = await chatAction(localStorage.token, actionId, {
			model: modelId,
			messages: messages.map((m) => ({
				id: m.id,
				role: m.role,
				content: m.content,
				info: m.info ? m.info : undefined,
				timestamp: m.timestamp,
				...(m.sources ? { sources: m.sources } : {})
			})),
			...(event ? { event: event } : {}),
			model_item: $models.find((m) => m.id === modelId),
			chat_id: chatId,
			session_id: $socket?.id,
			id: responseMessageId
		}).catch((error) => {
			toast.error(`${error}`);
			messages.at(-1).error = { content: error };
			return null;
		});

		if (res !== null && res.messages) {
			// Update chat history with the new messages
			for (const message of res.messages) {
				history.messages[message.id] = {
					...history.messages[message.id],
					...(history.messages[message.id].content !== message.content
						? { originalContent: history.messages[message.id].content }
						: {}),
					...message
				};
			}
		}

		if ($chatId == chatId && !$temporaryChatEnabled && res?.messages?.length) {
			const upsert = {};
			for (const message of res.messages) {
				if (message?.id && history.messages[message.id]) {
					upsert[message.id] = history.messages[message.id];
				}
			}
			applyChatHistoryPatch(localStorage.token, chatId, {
				upsert,
				expected_revision: revisionOf(chatId)
			}).catch(() => {});
		}
	};

	const getChatEventEmitter = async (modelId: string, chatId: string = '') => {
		return setInterval(() => {
			$socket?.emit('usage', {
				action: 'chat',
				model: modelId,
				chat_id: chatId
			});
		}, 1000);
	};

	const createMessagePair = async (userPrompt) => {
		prompt = '';
		if (selectedModels.length === 0) {
			toast.error($i18n.t('Model not selected'));
		} else {
			const modelId = selectedModels[0];
			const model = $models.filter((m) => m.id === modelId).at(0);

			const messages = createMessagesList(history, history.currentId);
			const parentMessage = messages.length !== 0 ? messages.at(-1) : null;

			const userMessageId = uuidv4();
			const responseMessageId = uuidv4();

			const userMessage = {
				id: userMessageId,
				parentId: parentMessage ? parentMessage.id : null,
				childrenIds: [responseMessageId],
				role: 'user',
				content: userPrompt ? userPrompt : `[PROMPT] ${userMessageId}`,
				timestamp: Math.floor(Date.now() / 1000)
			};

			const responseMessage = {
				id: responseMessageId,
				parentId: userMessageId,
				childrenIds: [],
				role: 'assistant',
				content: `[RESPONSE] ${responseMessageId}`,
				done: true,

				model: modelId,
				modelName: model.name ?? model.id,
				modelIdx: 0,
				timestamp: Math.floor(Date.now() / 1000)
			};

			if (parentMessage) {
				parentMessage.childrenIds.push(userMessageId);
				history.messages[parentMessage.id] = parentMessage;
			}
			history.messages[userMessageId] = userMessage;
			history.messages[responseMessageId] = responseMessage;

			history.currentId = responseMessageId;

			await tick();

			if (autoScroll) {
				scrollToBottom();
			}

			if (messages.length === 0) {
				await initChatHandler(history);
			} else {
				await saveChatHandler($chatId, history, [
					userMessageId,
					responseMessageId,
					parentMessage?.id
				]);
			}
		}
	};

	const addMessages = async ({ modelId, parentId, messages }) => {
		const model = $models.filter((m) => m.id === modelId).at(0);

		let parentMessage = history.messages[parentId];
		let currentParentId = parentMessage ? parentMessage.id : null;
		const createdIds = parentMessage?.id ? [parentMessage.id] : [];
		for (const message of messages) {
			let messageId = uuidv4();

			if (message.role === 'user') {
				const userMessage = {
					id: messageId,
					parentId: currentParentId,
					childrenIds: [],
					timestamp: Math.floor(Date.now() / 1000),
					...message
				};

				if (parentMessage) {
					parentMessage.childrenIds.push(messageId);
					history.messages[parentMessage.id] = parentMessage;
				}

				history.messages[messageId] = userMessage;
				createdIds.push(messageId);
				parentMessage = userMessage;
				currentParentId = messageId;
			} else {
				const responseMessage = {
					id: messageId,
					parentId: currentParentId,
					childrenIds: [],
					done: true,
					model: model.id,
					modelName: model.name ?? model.id,
					modelIdx: 0,
					timestamp: Math.floor(Date.now() / 1000),
					...message
				};

				if (parentMessage) {
					parentMessage.childrenIds.push(messageId);
					history.messages[parentMessage.id] = parentMessage;
				}

				history.messages[messageId] = responseMessage;
				createdIds.push(messageId);
				parentMessage = responseMessage;
				currentParentId = messageId;
			}
		}

		history.currentId = currentParentId;
		await tick();

		if (autoScroll) {
			scrollToBottom();
		}

		if (messages.length === 0) {
			await initChatHandler(history);
		} else {
			await saveChatHandler($chatId, history, createdIds);
		}
	};

	const speakLatestSentence = (message) => {
		if (navigator.vibrate && ($settings?.hapticFeedback ?? false)) {
			navigator.vibrate(5);
		}
		const messageContentParts = getMessageContentParts(
			message.content,
			$config?.audio?.tts?.split_on ?? 'punctuation'
		);
		messageContentParts.pop();
		if (
			messageContentParts.length > 0 &&
			messageContentParts[messageContentParts.length - 1] !== message.lastSentence
		) {
			message.lastSentence = messageContentParts[messageContentParts.length - 1];
			eventTarget.dispatchEvent(
				new CustomEvent('chat', {
					detail: {
						id: message.id,
						content: messageContentParts[messageContentParts.length - 1]
					}
				})
			);
		}
	};

	const paintCompletion = async (data, message, chatId) => {
		const { done, choices, content, error } = data;

		if (error) {
			const text =
				typeof error === 'string'
					? error
					: typeof error?.content === 'string'
						? error.content
						: typeof error?.message === 'string'
							? error.message
							: '';
			if (text) toast.error(text);
		}

		if (choices || content) speakLatestSentence(message);

		if (done) {
			taskIds = null;

			if ($settings.responseAutoCopy) {
				copyToClipboard(message.content);
			}

			if ($settings.responseAutoPlayback && !$showCallOverlay) {
				await tick();
				document.getElementById(`speak-button-${message.id}`)?.click();
			}

			const lastMessageContentPart =
				getMessageContentParts(
					message.content,
					$config?.audio?.tts?.split_on ?? 'punctuation'
				)?.at(-1) ?? '';
			if (lastMessageContentPart) {
				eventTarget.dispatchEvent(
					new CustomEvent('chat', {
						detail: { id: message.id, content: lastMessageContentPart }
					})
				);
			}
			eventTarget.dispatchEvent(
				new CustomEvent('chat:finish', {
					detail: {
						id: message.id,
						content: message.content
					}
				})
			);

			await chatCompletedHandler(
				chatId,
				message.model,
				message.id,
				createMessagesList(history, message.id)
			);
		}

		if (autoScroll) {
			scrollToBottom();
		} else if (choices || content || done) {
			noteNewMessagesBelow(message?.id || '');
		}
	};

	const bumpArtifactsSoon = () => {};

	const paintTranscript = (event) => {
		if (event?.chat_id !== get(chatId)) return;
		const type = event?.data?.type ?? null;
		const data = event?.data?.data ?? null;
		const message = event?.message_id ? history.messages?.[event.message_id] : null;
		history = history;
		if (!message) return;
		if (type === 'status') {
			if (data?.action === GENERATION_HEARTBEAT_ACTION) return;
			if (data?.done) bumpArtifactsSoon();
			if (autoScroll) scrollToBottom();
			return;
		}
		if (type === 'chat:completion') {
			paintCompletion(data, message, event.chat_id);
			bumpArtifactsSoon();
			return;
		}
		if (
			type === 'chat:message' ||
			type === 'replace' ||
			type === 'chat:message:files' ||
			type === 'files'
		) {
			bumpArtifactsSoon();
		}
		if (autoScroll) scrollToBottom();
		else noteNewMessagesBelow(message.id);
	};

	//////////////////////////
	// Chat functions
	//////////////////////////

	const submitPrompt = async (userPrompt, { _raw = false } = {}) => {
		if (!chatWritable) {
			toast.error($i18n.t('Clone this chat to continue it.'));
			return;
		}
		console.log('submitPrompt', userPrompt, $chatId);

		const messages = createMessagesList(history, history.currentId);
		const _selectedModels = selectedModels.map((modelId) =>
			$models.map((m) => m.id).includes(modelId) ? modelId : ''
		);
		if (JSON.stringify(selectedModels) !== JSON.stringify(_selectedModels)) {
			selectedModels = _selectedModels;
		}

		if (userPrompt === '' && files.length === 0) {
			toast.error($i18n.t('Please enter a prompt'));
			return;
		}
		if (selectedModels.includes('')) {
			toast.error($i18n.t('Model not selected'));
			return;
		}

		if (messages.length != 0 && messages.at(-1).done != true) {
			// Response not done
			return;
		}
		if (messages.length != 0 && messages.at(-1).error && !messages.at(-1).content) {
			// Error in response
			toast.error($i18n.t(`Oops! There was an error in the previous response.`));
			return;
		}
		if (
			files.length > 0 &&
			files.filter((file) => file.type !== 'image' && file.status === 'uploading').length > 0
		) {
			toast.error(
				$i18n.t(`Oops! There are files still uploading. Please wait for the upload to complete.`)
			);
			return;
		}
		if (
			($config?.file?.max_count ?? null) !== null &&
			files.length + chatFiles.length > $config?.file?.max_count
		) {
			toast.error(
				$i18n.t(`You can only chat with a maximum of {{maxCount}} file(s) at a time.`, {
					maxCount: $config?.file?.max_count
				})
			);
			return;
		}

		prompt = '';

		// Reset chat input textarea
		if (!($settings?.richTextInput ?? true)) {
			const chatInputElement = document.getElementById('chat-input');

			if (chatInputElement) {
				await tick();
				chatInputElement.style.height = '';
			}
		}

		pendingArtifactFiles = [];
		for (const item of files) {
			if (item.sandboxPath) continue;
			if (item.sourceFile instanceof File) {
				pendingArtifactFiles.push(item.sourceFile);
			} else if (item.type === 'image' && item.url) {
				pendingArtifactFiles.push(
					await fileFromDataUrl(item.url, item.name || `image-${Date.now()}`)
				);
			}
		}

		const _files = JSON.parse(
			JSON.stringify(files, (key, value) => (key === 'sourceFile' ? undefined : value))
		);
		chatFiles.push(..._files.filter((item) => ['doc', 'file', 'collection'].includes(item.type)));
		chatFiles = chatFiles.filter(
			// Remove duplicates
			(item, index, array) =>
				array.findIndex((i) => JSON.stringify(i) === JSON.stringify(item)) === index
		);

		files = [];
		prompt = '';

		// Create user message
		let userMessageId = uuidv4();
		let userMessage = {
			id: userMessageId,
			parentId: messages.length !== 0 ? messages.at(-1).id : null,
			childrenIds: [],
			role: 'user',
			content: userPrompt,
			files: _files.length > 0 ? _files : undefined,
			timestamp: Math.floor(Date.now() / 1000), // Unix epoch
			models: selectedModels
		};

		// Add message to history and Set currentId to messageId
		history.messages[userMessageId] = userMessage;
		history.currentId = userMessageId;

		// Append messageId to childrenIds of parent message
		if (messages.length !== 0) {
			history.messages[messages.at(-1).id].childrenIds.push(userMessageId);
		}

		// focus on chat input
		const chatInput = document.getElementById('chat-input');
		chatInput?.focus();

		saveSessionSelectedModels();

		await sendPrompt(history, userPrompt, userMessageId, { newChat: true });
	};

	const sendPrompt = async (
		_history,
		prompt: string,
		parentId: string,
		{ modelId = null, modelIdx = null, newChat = false } = {}
	) => {
		stopRequested = false;
		if (autoScroll) {
			scrollToBottom();
		}

		let _chatId = JSON.parse(JSON.stringify($chatId));
		_history = JSON.parse(JSON.stringify(_history));

		const responseMessageIds: Record<PropertyKey, string> = {};
		// If modelId is provided, use it, else use selected model
		let selectedModelIds = modelId
			? [modelId]
			: atSelectedModel !== undefined
				? [atSelectedModel.id]
				: selectedModels;

		// Create response messages for each selected model
		for (const [_modelIdx, modelId] of selectedModelIds.entries()) {
			const model = $models.filter((m) => m.id === modelId).at(0);

			if (model) {
				let responseMessageId = uuidv4();
				let responseMessage = {
					parentId: parentId,
					id: responseMessageId,
					childrenIds: [],
					role: 'assistant',
					content: '',
					model: model.id,
					modelName: model.name ?? model.id,
					modelIdx: modelIdx ? modelIdx : _modelIdx,
					timestamp: Math.floor(Date.now() / 1000) // Unix epoch
				};

				// Add message to history and Set currentId to messageId
				history.messages[responseMessageId] = responseMessage;
				history.currentId = responseMessageId;

				// Append messageId to childrenIds of parent message
				if (parentId !== null && history.messages[parentId]) {
					// Add null check before accessing childrenIds
					history.messages[parentId].childrenIds = [
						...history.messages[parentId].childrenIds,
						responseMessageId
					];
				}

				responseMessageIds[`${modelId}-${modelIdx ? modelIdx : _modelIdx}`] = responseMessageId;
			}
		}
		history = history;

		// Create new chat if newChat is true and first user message
		if (newChat && _history.messages[_history.currentId].parentId === null) {
			_chatId = await initChatHandler(_history);
		}

		await tick();

		_history = JSON.parse(JSON.stringify(history));

		const userMessage = _history.messages[parentId];
		await copyPendingArtifacts(_chatId, userMessage?.files || []);
		const sandboxPaths = (userMessage?.files ?? [])
			.map((item) => item?.sandboxPath)
			.filter(Boolean);
		if (sandboxPaths.length) {
			const note =
				sandboxPaths.length === 1
					? `\n\n[Uploaded to artifact sandbox: \`${sandboxPaths[0]}\`]`
					: `\n\n[Uploaded to artifact sandbox: ${sandboxPaths.map((p) => `\`${p}\``).join(', ')}]`;
			if (!(userMessage.content || '').includes('[Uploaded to artifact sandbox:')) {
				userMessage.content = `${userMessage.content || ''}${note}`;
			}
		}
		if (userMessage && get(chatId) === _chatId && history.messages[parentId]) {
			history.messages[parentId] = {
				...history.messages[parentId],
				files: userMessage.files,
				content: userMessage.content
			};
			history = history;
		}

		await Promise.all(
			selectedModelIds.map(async (modelId, _modelIdx) => {
				console.log('modelId', modelId);
				const model = $models.filter((m) => m.id === modelId).at(0);

				if (model) {
					const messages = createMessagesList(_history, parentId);
					// If there are image files, check if model is vision capable
					const hasImages = messages.some((message) =>
						message.files?.some((file) => file.type === 'image')
					);

					if (hasImages && !(model.info?.meta?.capabilities?.vision ?? true)) {
						toast.error(
							$i18n.t('Model {{modelName}} is not vision capable', {
								modelName: model.name ?? model.id
							})
						);
					}

					let responseMessageId =
						responseMessageIds[`${modelId}-${modelIdx ? modelIdx : _modelIdx}`];
					let responseMessage = _history.messages[responseMessageId];

					const chatEventEmitter = await getChatEventEmitter(model.id, _chatId);

					scrollToBottom();
					await sendPromptSocket(_history, model, responseMessageId, _chatId);

					if (chatEventEmitter) clearInterval(chatEventEmitter);
				} else {
					toast.error($i18n.t(`Model {{modelId}} not found`, { modelId }));
				}
			})
		);
	};

	const sendPromptSocket = async (_history, model, responseMessageId, _chatId) => {
		if (_chatId && _chatId !== 'local') {
			const bound = holdHistory(_chatId, history);
			if (bound) history = bound;
		}
		const responseMessage = _history.messages[responseMessageId];
		const userMessage = _history.messages[responseMessage.parentId];

		let files = JSON.parse(JSON.stringify(chatFiles));
		files.push(
			...(userMessage?.files ?? []).filter((item) =>
				['doc', 'file', 'collection'].includes(item.type)
			),
			...(responseMessage?.files ?? []).filter((item) => ['web_search_results'].includes(item.type))
		);
		// Remove duplicates
		files = files.filter(
			(item, index, array) =>
				array.findIndex((i) => JSON.stringify(i) === JSON.stringify(item)) === index
		);

		scrollToBottom();
		eventTarget.dispatchEvent(
			new CustomEvent('chat:start', {
				detail: {
					id: responseMessageId
				}
			})
		);
		await tick();

		const stream = model?.info?.params?.stream_response ?? true;
		const persistedTurn = Boolean(_chatId && _chatId !== 'local' && !$temporaryChatEnabled);
		if (persistedTurn) {
			beginLive(_chatId, responseMessageId);
			holdPendingTurn(_chatId, [userMessage?.id, responseMessageId]);
		}
		const transcript = createMessagesList(_history, responseMessageId);
		const firstTurn = transcript.filter((message) => message.role === 'user').length <= 1;

		let messages = [
			// Keep UI <details type="tool_calls"> intact. The backend expands them
			// into native assistant tool_calls + role:tool messages. Do not run
			// processDetails() here — that rewrote tools as <tool_calls> XML and
			// taught the model a fake tool dialect on follow-up turns.
			...createMessagesList(_history, responseMessageId).map((message) => ({
				...message,
				content:
					typeof message.content === 'string'
						? removeDetails(message.content, ['reasoning', 'code_interpreter'])
						: message.content
			}))
		];

		messages = messages
			.map((message, idx, arr) => ({
				role: message.role,
				...(message.tool_calls ? { tool_calls: message.tool_calls } : {}),
				...(message.tool_call_id ? { tool_call_id: message.tool_call_id } : {}),
				...((message.files?.filter((file) => file.type === 'image').length > 0 ?? false) &&
				message.role === 'user'
					? {
							content: [
								{
									type: 'text',
									text: message?.merged?.content ?? message.content
								},
								...message.files
									.filter((file) => file.type === 'image')
									.map((file) => ({
										type: 'image_url',
										image_url: {
											url: file.url
										}
									}))
							]
						}
					: {
							content: message?.merged?.content ?? message.content
						})
			}))
			.filter((message) => {
				if (message?.role === 'user' || message?.role === 'system') return true;
				if (message?.role === 'tool') return true;
				if (message?.tool_calls?.length) return true;
				const content = message?.content;
				if (typeof content === 'string') return !!content.trim();
				return Array.isArray(content) ? content.length > 0 : !!content;
			});

		const completionBody = {
				stream: stream,
				model: model.id,
				...(persistedTurn
					? {
							turn: {
								parent_id: userMessage?.parentId ?? null,
								expected_revision: revisionOf(_chatId),
								user_message: userMessage,
								assistant_message: {
									id: responseMessageId,
									parentId: userMessage?.id ?? null,
									childrenIds: [],
									role: 'assistant',
									content: '',
									done: false,
									model: model.id,
									modelName: model.name ?? model.id,
									modelIdx: responseMessage?.modelIdx ?? 0,
									timestamp: responseMessage?.timestamp
								}
							}
						}
					: { messages }),

				files: (files?.length ?? 0) > 0 ? files : undefined,
				tool_ids: selectedToolIds.length > 0 ? selectedToolIds : undefined,
				tool_servers: $toolServers,

				features: {
					image_generation:
						$config?.features?.enable_image_generation &&
						($user?.role === 'admin' || $user?.permissions?.features?.image_generation)
							? imageGenerationEnabled
							: false,
					code_interpreter:
						$config?.features?.enable_code_interpreter &&
						($user?.role === 'admin' || $user?.permissions?.features?.code_interpreter)
							? codeInterpreterEnabled
							: false,
					web_search:
						$config?.features?.enable_web_search &&
						($user?.role === 'admin' || $user?.permissions?.features?.web_search)
							? webSearchEnabled || ($settings?.webSearch ?? false) === 'always'
							: false
				},
				variables: {
					...getPromptVariables(
						$user?.name,
						$settings?.userLocation
							? await getAndUpdateUserLocation(localStorage.token).catch((err) => {
									console.error(err);
									return undefined;
								})
							: undefined
					)
				},
				model_item: $models.find((m) => m.id === model.id),

				session_id: $socket?.id,
				chat_id: _chatId,
				id: responseMessageId,

				...(!$temporaryChatEnabled &&
				(selectedModels[0] === model.id || atSelectedModel !== undefined)
					? (() => {
							const untitled =
								($chatTitle || '').trim() === '' ||
								$chatTitle === 'New Chat' ||
								$chatTitle === $i18n.t('New Chat');
							const background_tasks = {
								...(untitled && ($settings?.title?.auto ?? true)
									? { title_generation: true }
									: {}),
								...(firstTurn ? { tags_generation: $settings?.autoTags ?? true } : {})
							};
							return Object.keys(background_tasks).length
								? { background_tasks }
								: {};
						})()
					: {}),

				...(stream && (model.info?.meta?.capabilities?.usage ?? false)
					? {
							stream_options: {
								include_usage: true
							}
						}
					: {})
		};
		const res = await generateOpenAIChatCompletion(
			localStorage.token,
			completionBody,
			`${WEBUI_BASE_URL}/api`
		).catch(async (error) => {
			if (isChatConflict(error) || isChatBusy(error)) {
				let retried = null;
				const recovered = await recoverSendConflict({
					refetch: () => refetchChat(localStorage.token, _chatId),
					retry: async () => {
						if (completionBody.turn) {
							// Another tab added to this conversation. Send this
							// message after the newest one instead of branching.
							const parentId = moveTurnToEnd(_chatId, completionBody.turn.user_message.id);
							completionBody.turn.parent_id = parentId;
							completionBody.turn.user_message = {
								...completionBody.turn.user_message,
								parentId
							};
							completionBody.turn.expected_revision = revisionOf(_chatId);
							if (get(chatId) === _chatId) history = history;
						}
						retried = await generateOpenAIChatCompletion(
							localStorage.token,
							completionBody,
							`${WEBUI_BASE_URL}/api`
						);
					}
				});
				if (recovered === 'retried') return retried;
			}
			const reason =
				writeErrorMessage(error) || formatGenerationRequestError(error);
			responseMessage.error = { content: reason };
			responseMessage.done = true;
			endLive(responseMessageId);
			toast.error(reason);
			if (get(chatId) === _chatId) {
				history.messages[responseMessageId] = responseMessage;
				history.currentId = responseMessageId;
			}
			return null;
		});

		if (res?.error) {
			await handleOpenAIError(res.error, responseMessage);
			return;
		}
		if (get(chatId) !== _chatId) return;

		if (res) {
			if (res.task_id) {
				if (stopRequested) {
					// User hit Stop before task_id arrived — cancel immediately.
					await stopTask(localStorage.token, res.task_id).catch(() => null);
					taskIds = null;
				} else if (taskIds) {
					taskIds.push(res.task_id);
				} else {
					taskIds = [res.task_id];
				}
			}
		}

		await tick();
		if (get(chatId) !== _chatId) return;
		if (autoScroll) {
			scrollToBottom();
		} else {
			newMessagesBelow = true;
		}
	};

	const handleOpenAIError = async (error, responseMessage) => {
		let errorMessage = '';
		let innerError;

		if (error) {
			innerError = error;
		}

		console.error(innerError);
		if (typeof innerError === 'string') {
			toast.error(innerError);
			errorMessage = innerError;
		} else if (innerError && 'detail' in innerError) {
			// FastAPI error
			toast.error(innerError.detail);
			errorMessage = innerError.detail;
		} else if (innerError && typeof innerError.content === 'string') {
			toast.error(innerError.content);
			errorMessage = innerError.content;
		} else if ('error' in innerError) {
			// OpenAI error
			if ('message' in innerError.error) {
				toast.error(innerError.error.message);
				errorMessage = innerError.error.message;
			} else {
				toast.error(innerError.error);
				errorMessage = innerError.error;
			}
		} else if ('message' in innerError) {
			// OpenAI error
			toast.error(innerError.message);
			errorMessage = innerError.message;
		}

		responseMessage.error = {
			content: isUsageLimitMessage(errorMessage)
				? errorMessage
				: $i18n.t(`Uh-oh! There was an issue with the response.`) + '\n' + errorMessage
		};
		responseMessage.done = true;
		endLive(responseMessage.id);
		taskIds = null;

		if (responseMessage.statusHistory) {
			responseMessage.statusHistory = responseMessage.statusHistory.filter(
				(status) => status.action !== 'knowledge_search'
			);
		}

		if (history?.messages?.[responseMessage.id]) {
			history.messages[responseMessage.id] = responseMessage;
		}
	};

	const markAssistantResponsesDone = (parentId: string | null | undefined) => {
		if (!parentId) {
			return;
		}
		const parent = history.messages[parentId];
		if (!parent?.childrenIds) {
			return;
		}
		for (const messageId of parent.childrenIds) {
			const message = history.messages[messageId];
			if (message?.role === 'assistant') {
				message.done = true;
				message.content = clearSpinningToolCalls(message.content ?? '');
				if (message.statusHistory?.length) {
					message.statusHistory = message.statusHistory.map((status) =>
						status?.done === false ? { ...status, done: true, hidden: true } : status
					);
				}
			}
		}
	};

	const stopResponse = async () => {
		// Optimistic UI: flip the stop button / spinners immediately.
		// The backend stop endpoint awaits task cancellation, which can stall
		// while the model is mid-think / mid-stream.
		stopRequested = true;
		const idsToStop = taskIds ? [...taskIds] : [];
		taskIds = null;
		const stoppingId = history.currentId;
		if (stoppingId) endLive(stoppingId);

		const responseMessage = history.messages[history.currentId];
		if (responseMessage?.role === 'assistant' && responseMessage.done !== true) {
			if (responseMessage.parentId) {
				markAssistantResponsesDone(responseMessage.parentId);
			} else {
				responseMessage.done = true;
				responseMessage.content = clearSpinningToolCalls(responseMessage.content ?? '');
				if (responseMessage.statusHistory?.length) {
					responseMessage.statusHistory = responseMessage.statusHistory.map((status) =>
						status?.done === false ? { ...status, done: true, hidden: true } : status
					);
				}
				history.messages[history.currentId] = responseMessage;
			}
			history = history;
		}

		if (autoScroll) {
			scrollToBottom();
		}

		await tick();

		if (responseMessage?.id) endLive(responseMessage.id);
		for (const taskId of idsToStop) {
			stopTask(localStorage.token, taskId).catch((error) => {
				toast.error(`${error}`);
			});
		}

	};

	const submitMessage = async (parentId, prompt) => {
		let userPrompt = prompt;
		let userMessageId = uuidv4();

		let userMessage = {
			id: userMessageId,
			parentId: parentId,
			childrenIds: [],
			role: 'user',
			content: userPrompt,
			models: selectedModels
		};

		if (parentId !== null) {
			history.messages[parentId].childrenIds = [
				...history.messages[parentId].childrenIds,
				userMessageId
			];
		}

		history.messages[userMessageId] = userMessage;
		history.currentId = userMessageId;

		await tick();

		if (autoScroll) {
			scrollToBottom();
		}

		await sendPrompt(history, userPrompt, userMessageId);
	};

	const regenerateResponse = async (message) => {
		console.log('regenerateResponse');

		if (history.currentId) {
			let userMessage = history.messages[message.parentId];
			let userPrompt = userMessage.content;

			if (autoScroll) {
				scrollToBottom();
			}

			if ((userMessage?.models ?? [...selectedModels]).length == 1) {
				// If user message has only one model selected, sendPrompt automatically selects it for regeneration
				await sendPrompt(history, userPrompt, userMessage.id);
			} else {
				// If there are multiple models selected, use the model of the response message for regeneration
				// e.g. many model chat
				await sendPrompt(history, userPrompt, userMessage.id, {
					modelId: message.model,
					modelIdx: message.modelIdx
				});
			}
		}
	};

	const continueResponse = async () => {
		console.log('continueResponse');
		const _chatId = JSON.parse(JSON.stringify($chatId));

		if (history.currentId && history.messages[history.currentId].done == true) {
			const responseMessage = history.messages[history.currentId];
			responseMessage.done = false;
			await tick();

			const model = $models
				.filter((m) => m.id === (responseMessage?.selectedModelId ?? responseMessage.model))
				.at(0);

			if (model) {
				await sendPromptSocket(history, model, responseMessage.id, _chatId);
			}
		}
	};

	const mergeResponses = async (messageId, responses, _chatId) => {
		console.log('mergeResponses', messageId, responses);
		const message = history.messages[messageId];
		const mergedResponse = {
			status: true,
			content: ''
		};
		message.merged = mergedResponse;
		history.messages[messageId] = message;

		try {
			const [res, controller] = await generateMoACompletion(
				localStorage.token,
				message.model,
				history.messages[message.parentId].content,
				responses
			);

			if (res && res.ok && res.body) {
				const textStream = await createOpenAITextStream(res.body, $settings.splitLargeChunks);
				for await (const update of textStream) {
					const { value, done, sources, error, usage } = update;
					if (error || done) {
						break;
					}

					if (mergedResponse.content == '' && value == '\n') {
						continue;
					} else {
						mergedResponse.content += value;
						history.messages[messageId] = message;
					}

					if (autoScroll) {
						scrollToBottom();
					}
				}

				await saveChatHandler(_chatId, history, [messageId]);
			} else {
				console.error(res);
			}
		} catch (e) {
			console.error(e);
		}
	};

	const initChatHandler = async (history) => {
		let _chatId = $chatId;

		if (!$temporaryChatEnabled) {
			void openArtifactsPanel();
			chat = await createNewChat(
				localStorage.token,
				{
					id: _chatId,
					title: $i18n.t('New Chat'),
					models: selectedModels,
					params: params,
					history: history,
					messages: createMessagesList(history, history.currentId),
					tags: [],
					timestamp: Date.now()
				},
				get(activeOrganizationId)
			);

			_chatId = chat.id;
			putChat(chat, null);
			await chatId.set(_chatId);

			const createdAt = chat.updated_at ?? Math.floor(Date.now() / 1000);
			chats.update((list) => {
				const row = {
					id: chat.id,
					title: chat.title ?? chat.chat?.title,
					updated_at: createdAt,
					created_at: chat.created_at ?? createdAt,
					folder_id: chat.folder_id ?? null,
					visibility: chat.visibility,
					user_id: chat.user_id,
					pinned: !!chat.pinned,
					time_range: getTimeRange(createdAt)
				};
				const items = (list ?? []).filter((item) => item.id !== row.id);
				items.unshift(row);
				return items;
			});

			window.history.replaceState(history.state, '', `/c/${_chatId}`);
		} else {
			_chatId = 'local';
			await chatId.set('local');
		}
		await tick();

		return _chatId;
	};

	const saveChatHandler = async (_chatId, history, messageIds = []) => {
		if ($temporaryChatEnabled || $chatId !== _chatId || !messageIds?.length) return;
		const upsert = {};
		for (const id of messageIds) {
			if (id && history.messages?.[id]) upsert[id] = history.messages[id];
		}
		if (!Object.keys(upsert).length) return;
		try {
			const saved = await applyChatHistoryPatch(localStorage.token, _chatId, {
				upsert,
				expected_revision: revisionOf(_chatId)
			});
			if (saved) {
				chat = saved;
				putChat(saved, null);
			}
		} catch (error) {
			console.error(error);
			if (isChatConflict(error)) {
				const recovered = await recoverEditConflict({
					refetch: async () => {
						const document = await getChatById(localStorage.token, _chatId).catch(() => null);
						if (document && $chatId === _chatId) applyChatDocument(document);
					},
					reapply: async () => {
						const saved = await applyChatHistoryPatch(localStorage.token, _chatId, {
							upsert,
							expected_revision: revisionOf(_chatId)
						});
						if (saved) {
							chat = saved;
							putChat(saved, null);
						}
					}
				});
				if (recovered === 'reapplied') return;
				toast.error(writeErrorMessage(error) || CHAT_CONFLICT_MESSAGE);
				return;
			}
			const detail = typeof error?.detail === 'string' ? error.detail : '';
			toast.error(
				detail ? `${$i18n.t('Failed to save chat')}: ${detail}` : $i18n.t('Failed to save chat')
			);
		}
	};
</script>

<svelte:head>
	<title>
		{$chatTitle
			? `${$chatTitle.length > 30 ? `${$chatTitle.slice(0, 30)}...` : $chatTitle} | ${$WEBUI_NAME}`
			: `${$WEBUI_NAME}`}
	</title>
</svelte:head>

<audio id="audioElement" src="" style="display: none;" />

<EventConfirmDialog
	bind:show={showEventConfirmation}
	title={eventConfirmationTitle}
	message={eventConfirmationMessage}
	input={eventConfirmationInput}
	inputPlaceholder={eventConfirmationInputPlaceholder}
	inputValue={eventConfirmationInputValue}
	on:confirm={(e) => {
		if (e.detail) {
			eventCallback(e.detail);
		} else {
			eventCallback(true);
		}
	}}
	on:cancel={() => {
		eventCallback(false);
	}}
/>

<div
	class="h-screen max-h-[100dvh] transition-width duration-200 ease-in-out {$showSidebar
		? '  md:max-w-[calc(100%-260px)]'
		: ' '} w-full max-w-full flex flex-col relative"
	id="chat-container"
>
	{#if !loading && ($settings?.backgroundImageUrl ?? null)}
		<div
			class="absolute {$showSidebar
				? 'md:max-w-[calc(100%-260px)] md:translate-x-[260px]'
				: ''} top-0 left-0 w-full h-full bg-cover bg-center bg-no-repeat"
			style="background-image: url({$settings.backgroundImageUrl})  "
		/>

		<div
			class="absolute top-0 left-0 w-full h-full bg-linear-to-t from-white to-white/85 dark:from-gray-900 dark:to-gray-900/90 z-0"
		/>
	{/if}

	<PaneGroup direction="horizontal" class="w-full h-full">
		<Pane defaultSize={50} class="h-full flex relative max-w-full flex-col">
			{#if loading}
				<div class="flex items-center justify-center h-full w-full">
					<div class="m-auto">
						<Spinner />
					</div>
				</div>
			{:else}
				<Navbar
					bind:this={navbarElement}
					chat={{
						id: $chatId,
						chat: {
							title: $chatTitle,
							models: selectedModels,
							params: params,
							history: history,
							timestamp: Date.now()
						}
					}}
					{history}
					title={$chatTitle}
					bind:selectedModels
					shareEnabled={!!history.currentId}
					{initNewChat}
				/>

				<div class="flex flex-col flex-auto z-10 w-full @container">
					{#if $settings?.landingPageMode === 'chat' || createMessagesList(history, history.currentId).length > 0}
						<div
							class=" pb-2.5 flex flex-col justify-between w-full flex-auto overflow-auto h-0 max-w-full z-10 scrollbar-hidden"
							id="messages-container"
							bind:this={messagesContainerElement}
							use:stickToEnd
							style="overflow-anchor: none"
							on:load|capture={() => {
								if (!settleScroll || !messagesContainerElement) return;
								if (autoScroll) {
									pinScrollToEnd();
									return;
								}
								placeSavedScroll(messagesContainerElement);
							}}
							on:scroll={() => {
								if (pinningScroll || !messagesContainerElement || !scrollChatId) return;
								const element = messagesContainerElement;
								const atBottom =
									element.scrollHeight - element.scrollTop <= element.clientHeight + 5;
								const previous = chatScrollFor(scrollChatId);
								if (tailHeld(element, previous)) {
									autoScroll = true;
									window.clearTimeout(scrollStopTimer);
									pinScrollToEnd();
									return;
								}
								autoScroll = atBottom;
								if (atBottom) newMessagesBelow = false;
								settleScroll = false;
								const id = scrollChatId;
								// Opening the sidebar resizes the pane and can emit scroll
								// without the reader moving. Keep the line they chose.
								if (
									previous &&
									!previous.atBottom &&
									Math.abs(element.scrollTop - previous.top) < 2
								) {
									return;
								}
								window.clearTimeout(scrollStopTimer);
								scrollStopTimer = window.setTimeout(() => {
									if (pinningScroll || scrollChatId !== id || !messagesContainerElement) return;
									captureScroll(id, messagesContainerElement);
								}, 150);
							}}
						>
							<div class=" min-h-full w-full flex flex-col">
								{#if messagesComponent}
									<svelte:component
										this={messagesComponent}
										chatId={$chatId}
										bind:history
										{paintKey}
										bind:autoScroll
										bind:prompt
										{selectedModels}
										{atSelectedModel}
										{sendPrompt}
										{showMessage}
										{submitMessage}
										{continueResponse}
										{regenerateResponse}
										{mergeResponses}
										{chatActionHandler}
										{addMessages}
										bottomPadding={files.length > 0}
									/>
								{/if}
							</div>
						</div>

						<div class=" pb-[1rem]">
							{#if !chatWritable}
								<div class="mx-auto w-full max-w-[58rem] px-2.5 mb-2">
									<div
										class="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 px-2.5 py-1.5 text-xs text-gray-700 dark:text-gray-300"
									>
										<div class="min-w-0 flex-1 leading-snug">
											{$i18n.t('Owned by')}
											<span class="font-medium">{chatOwnerName || $i18n.t('a teammate')}</span>.
											{$i18n.t('Clone to continue.')}
										</div>
										<button
											class="shrink-0 rounded-md bg-gray-900 dark:bg-white text-white dark:text-gray-900 px-2 py-0.5 text-[11px]"
											on:click={async () => {
												const cloned = await cloneChatById(localStorage.token, $chatId).catch(
													(error) => {
														toast.error(`${error}`);
														return null;
													}
												);
												if (cloned) {
													await goto(`/c/${cloned.id}`);
												}
											}}
										>
											{$i18n.t('Clone to continue')}
										</button>
									</div>
								</div>
							{:else}
							<MessageInput
								{history}
								{taskIds}
								{selectedModels}
								bind:files
								bind:prompt
								bind:autoScroll
								bind:newMessagesBelow
								bind:selectedToolIds
								bind:imageGenerationEnabled
								bind:codeInterpreterEnabled
								bind:webSearchEnabled
								bind:atSelectedModel
								toolServers={$toolServers}
								transparentBackground={$settings?.backgroundImageUrl ?? false}
								{stopResponse}
								{createMessagePair}
								onChange={(input) => {
									if (input.prompt) {
										localStorage.setItem(`chat-input-${$chatId}`, JSON.stringify(input));
									} else {
										localStorage.removeItem(`chat-input-${$chatId}`);
									}
								}}
								on:upload={async (e) => {
									const { type, data } = e.detail;

									if (type === 'web') {
										await uploadWeb(data);
									} else if (type === 'youtube') {
										await uploadYoutubeTranscription(data);
									} else if (type === 'google-drive') {
										await uploadGoogleDriveFile(data);
									}
								}}
								on:submit={async (e) => {
									if (e.detail || files.length > 0) {
										await tick();
										submitPrompt(
											($settings?.richTextInput ?? true)
												? e.detail.replaceAll('\n\n', '\n')
												: e.detail
										);
									}
								}}
							/>
							{/if}

							<div
								class="absolute bottom-1 text-xs text-gray-500 text-center line-clamp-1 right-0 left-0"
							>
								<!-- {$i18n.t('LLMs can make mistakes. Verify important information.')} -->
							</div>
						</div>
					{:else}
						<div class="overflow-auto w-full h-full flex items-center">
							<Placeholder
								{history}
								{selectedModels}
								bind:files
								bind:prompt
								bind:autoScroll
								bind:selectedToolIds
								bind:imageGenerationEnabled
								bind:codeInterpreterEnabled
								bind:webSearchEnabled
								bind:atSelectedModel
								transparentBackground={$settings?.backgroundImageUrl ?? false}
								toolServers={$toolServers}
								{stopResponse}
								{createMessagePair}
								on:upload={async (e) => {
									const { type, data } = e.detail;

									if (type === 'web') {
										await uploadWeb(data);
									} else if (type === 'youtube') {
										await uploadYoutubeTranscription(data);
									}
								}}
								on:submit={async (e) => {
									if (e.detail || files.length > 0) {
										await tick();
										submitPrompt(
											($settings?.richTextInput ?? true)
												? e.detail.replaceAll('\n\n', '\n')
												: e.detail
										);
									}
								}}
							/>
						</div>
					{/if}
				</div>
			{/if}
			</Pane>

			<ChatControls
				bind:this={controlPaneComponent}
				bind:history
				bind:files
				bind:pane={controlPane}
				chatId={$chatId}
				modelId={selectedModelIds?.at(0) ?? null}
				{submitPrompt}
				{stopResponse}
				{showMessage}
				{eventTarget}
			/>
		</PaneGroup>

		{#if !loading && $chatId && $chatId !== 'local' && !($showControls && $showArtifacts)}
			<button
				type="button"
				class="hidden md:flex absolute right-0 top-1/2 -translate-y-1/2 z-40 flex-col items-center gap-1 rounded-l-xl border border-r-0 border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-1.5 py-3 shadow-md text-gray-800 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-750"
				on:click={() => openArtifactsPanel()}
				aria-label="Open artifacts"
			>
				<DocumentChartBar className="size-4" />
				<span
					class="text-[10px] font-semibold tracking-wide"
					style="writing-mode: vertical-rl; text-orientation: mixed;"
				>
					{$i18n.t('Artifacts')}
				</span>
			</button>
		{/if}
</div>
