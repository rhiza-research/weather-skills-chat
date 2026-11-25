<script lang="ts">
	import Download from '$lib/components/icons/Download.svelte';
	import Cog6 from '$lib/components/icons/Cog6.svelte';
	import { toast } from 'svelte-sonner';
	import { DropdownMenu } from 'bits-ui';
	import { getContext } from 'svelte';

	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import { downloadChatAsPDF } from '$lib/apis/utils';
	import { copyToClipboard, createMessagesList } from '$lib/utils';

	import {
		showOverview,
		showControls,
		showArtifacts,
		showCallOverlay,
		temporaryChatEnabled,
		theme,
		user,
		organizations,
		activeOrganizationId
	} from '$lib/stores';
	import { flyAndScale } from '$lib/utils/transitions';

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import Tags from '$lib/components/chat/Tags.svelte';
	import Map from '$lib/components/icons/Map.svelte';
	import Clipboard from '$lib/components/icons/Clipboard.svelte';
	import Cube from '$lib/components/icons/Cube.svelte';
	import Share from '$lib/components/icons/Share.svelte';
	import DocumentDuplicate from '$lib/components/icons/DocumentDuplicate.svelte';
	import { getChatById, updateChatVisibilityById } from '$lib/apis/chats';
	import { refreshSidebar } from '$lib/chat/reconnect';

	const i18n = getContext('i18n');

	export let shareEnabled: boolean = false;
	export let shareHandler: Function;
	export let cloneToOrgHandler: Function = () => {};
	export let downloadHandler: Function;
	export let onVisibilityChange: (visibility: string) => void = () => {};

	// export let tagHandler: Function;

	export let chat;
	export let onClose: Function = () => {};

	const getChatAsText = async () => {
		const history = chat.chat.history;
		const messages = createMessagesList(history, history.currentId);
		const chatText = messages.reduce((a, message, i, arr) => {
			return `${a}### ${message.role.toUpperCase()}\n${message.content}\n\n`;
		}, '');

		return chatText.trim();
	};

	const downloadTxt = async () => {
		const chatText = await getChatAsText();

		let blob = new Blob([chatText], {
			type: 'text/plain'
		});

		saveAs(blob, `chat-${chat.chat.title}.txt`);
	};

	const downloadPdf = async () => {
		const containerElement = document.getElementById('messages-container');

		if (containerElement) {
			try {
				const [{ default: html2canvas }, { jsPDF }] = await Promise.all([
					import('html2canvas-pro'),
					import('jspdf')
				]);
				const isDarkMode = document.documentElement.classList.contains('dark');

				console.log('isDarkMode', isDarkMode);

				// Define a fixed virtual screen size
				const virtualWidth = 800; // Fixed width (adjust as needed)
				// Clone the container to avoid layout shifts
				const clonedElement = containerElement.cloneNode(true);
				clonedElement.classList.add('text-black');
				clonedElement.classList.add('dark:text-white');
				clonedElement.style.width = `${virtualWidth}px`; // Apply fixed width
				clonedElement.style.height = 'auto'; // Allow content to expand

				document.body.appendChild(clonedElement); // Temporarily add to DOM

				// Render to canvas with predefined width
				const canvas = await html2canvas(clonedElement, {
					backgroundColor: isDarkMode ? '#000' : '#fff',
					useCORS: true,
					scale: 2, // Keep at 1x to avoid unexpected enlargements
					width: virtualWidth, // Set fixed virtual screen width
					windowWidth: virtualWidth // Ensure consistent rendering
				});

				document.body.removeChild(clonedElement); // Clean up temp element

				const imgData = canvas.toDataURL('image/png');

				// A4 page settings
				const pdf = new jsPDF('p', 'mm', 'a4');
				const imgWidth = 210; // A4 width in mm
				const pageHeight = 297; // A4 height in mm

				// Maintain aspect ratio
				const imgHeight = (canvas.height * imgWidth) / canvas.width;
				let heightLeft = imgHeight;
				let position = 0;

				// Set page background for dark mode
				if (isDarkMode) {
					pdf.setFillColor(0, 0, 0);
					pdf.rect(0, 0, imgWidth, pageHeight, 'F'); // Apply black bg
				}

				pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight);
				heightLeft -= pageHeight;

				// Handle additional pages
				while (heightLeft > 0) {
					position -= pageHeight;
					pdf.addPage();

					if (isDarkMode) {
						pdf.setFillColor(0, 0, 0);
						pdf.rect(0, 0, imgWidth, pageHeight, 'F');
					}

					pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight);
					heightLeft -= pageHeight;
				}

				pdf.save(`chat-${chat.chat.title}.pdf`);
			} catch (error) {
				console.error('Error generating PDF', error);
			}
		}
	};

	const toggleVisibility = async () => {
		const visibility = chat.visibility === 'organization' ? 'private' : 'organization';
		try {
			await updateChatVisibilityById(localStorage.token, chat.id, visibility);
			onVisibilityChange(visibility);
			toast.success(
				$i18n.t(visibility === 'organization' ? 'Shared with organization' : 'Moved to private')
			);
			await refreshSidebar(true);
		} catch (error) {
			toast.error(`${error}`);
		}
	};

	const downloadJSONExport = async () => {
		if (chat.id) {
			let chatObj = null;

			if (chat.id === 'local' || $temporaryChatEnabled) {
				chatObj = chat;
			} else {
				chatObj = await getChatById(localStorage.token, chat.id);
			}

			let blob = new Blob([JSON.stringify([chatObj])], {
				type: 'application/json'
			});
			saveAs(blob, `chat-export-${Date.now()}.json`);
		}
	};
</script>

<Dropdown
	on:change={(e) => {
		if (e.detail === false) {
			onClose();
		}
	}}
>
	<slot />

	<div slot="content">
		<DropdownMenu.Content
			class="w-full max-w-[280px] rounded-xl px-1 py-1.5 z-50 bg-panel dark:text-white shadow-lg"
			sideOffset={8}
			side="bottom"
			align="end"
			transition={flyAndScale}
		>
			<!-- <DropdownMenu.Item
				class="menu-item"
				on:click={async () => {
					await showSettings.set(!$showSettings);
				}}
			>
				<Cog6 className="size-4" />
				<div class="flex items-center">{$i18n.t('Settings')}</div>
			</DropdownMenu.Item> -->

			<!-- Only the owner can share; others clone the chat first. -->
			{#if !$temporaryChatEnabled && (!chat.user_id || chat.user_id === $user?.id)}
				<DropdownMenu.Item
					class="menu-item"
					id="chat-share-button"
					on:click={() => {
						shareHandler();
					}}
				>
					<Share className="size-4" />
					<div class="flex items-center">{$i18n.t('Share via link')}</div>
				</DropdownMenu.Item>

				<!-- The personal org's id is the user's id; its chats can't be shared. -->
				{#if chat.organization_id && chat.organization_id !== $user?.id}
					<DropdownMenu.Item
						class="flex gap-2 items-center px-3 py-2 text-sm  cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md"
						on:click={toggleVisibility}
					>
						<Share />
						<div class="flex items-center">
							{chat.visibility === 'organization'
								? $i18n.t('Make private')
								: $i18n.t('Share chat with this organization')}
						</div>
					</DropdownMenu.Item>
				{/if}

				{#if chat.id && ($organizations ?? []).some((org) => org.id !== $activeOrganizationId)}
					<DropdownMenu.Item
						class="flex gap-2 items-center px-3 py-2 text-sm cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-md"
						on:click={() => cloneToOrgHandler()}
					>
						<DocumentDuplicate className="size-4" strokeWidth="1.5" />
						<div class="flex items-center">{$i18n.t('Clone chat to another organization')}</div>
					</DropdownMenu.Item>
				{/if}
			{/if}

			<DropdownMenu.Item
				class="menu-item"
				id="chat-overview-button"
				on:click={async () => {
					await showControls.set(true);
					await showOverview.set(true);
					await showArtifacts.set(false);
				}}
			>
				<Map className=" size-4" strokeWidth="1.5" />
				<div class="flex items-center">{$i18n.t('Overview')}</div>
			</DropdownMenu.Item>

			<DropdownMenu.Item
				class="menu-item"
				id="chat-overview-button"
				on:click={async () => {
					localStorage.artifactsPanelOpen = 'true';
					await showOverview.set(false);
					await showCallOverlay.set(false);
					await showArtifacts.set(true);
					await showControls.set(true);
				}}
			>
				<Cube className=" size-4" strokeWidth="1.5" />
				<div class="flex items-center">{$i18n.t('Artifacts')}</div>
			</DropdownMenu.Item>

			<DropdownMenu.Sub>
				<DropdownMenu.SubTrigger
					class="menu-item"
				>
					<Download className="size-4" />

					<div class="flex items-center">{$i18n.t('Download')}</div>
				</DropdownMenu.SubTrigger>
				<DropdownMenu.SubContent
					class="w-full rounded-xl px-1 py-1.5 z-50 bg-panel dark:text-white shadow-lg"
					transition={flyAndScale}
					sideOffset={8}
				>
					<DropdownMenu.Item
						class="menu-item"
						on:click={() => {
							downloadJSONExport();
						}}
					>
						<div class="flex items-center line-clamp-1">{$i18n.t('Export chat (.json)')}</div>
					</DropdownMenu.Item>
					<DropdownMenu.Item
						class="menu-item"
						on:click={() => {
							downloadTxt();
						}}
					>
						<div class="flex items-center line-clamp-1">{$i18n.t('Plain text (.txt)')}</div>
					</DropdownMenu.Item>

					<DropdownMenu.Item
						class="menu-item"
						on:click={() => {
							downloadPdf();
						}}
					>
						<div class="flex items-center line-clamp-1">{$i18n.t('PDF document (.pdf)')}</div>
					</DropdownMenu.Item>
				</DropdownMenu.SubContent>
			</DropdownMenu.Sub>

			<DropdownMenu.Item
				class="menu-item"
				id="chat-copy-button"
				on:click={async () => {
					const res = await copyToClipboard(await getChatAsText()).catch((e) => {
						console.error(e);
					});

					if (res) {
						toast.success($i18n.t('Copied to clipboard'));
					}
				}}
			>
				<Clipboard className=" size-4" strokeWidth="1.5" />
				<div class="flex items-center">{$i18n.t('Copy')}</div>
			</DropdownMenu.Item>

			{#if !$temporaryChatEnabled}
				<hr class="border-line my-0.5" />

				<div class="flex">
					<Tags chatId={chat.id} />
				</div>
			{/if}
		</DropdownMenu.Content>
	</div>
</Dropdown>
