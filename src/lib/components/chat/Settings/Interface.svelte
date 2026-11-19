<script lang="ts">
	import { setDefaultPromptSuggestions } from '$lib/apis/configs';
	import { config, models, settings, user } from '$lib/stores';
	import { createEventDispatcher, onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { updateUserInfo } from '$lib/apis/users';
	import { getUserPosition } from '$lib/utils';
	import SettingToggle from '$lib/components/common/SettingToggle.svelte';
	import SettingRow from '$lib/components/common/SettingRow.svelte';
	const dispatch = createEventDispatcher();

	const i18n = getContext('i18n');

	export let saveSettings: Function;

	let backgroundImageUrl = null;
	let inputFiles = null;
	let filesInputElement;

	// Addons
	let titleAutoGenerate = true;
	let autoTags = true;

	let responseAutoCopy = false;
	let widescreenMode = false;
	let splitLargeChunks = false;
	let scrollOnBranchChange = true;
	let userLocation = false;

	// Interface
	let defaultModelId = '';
	let showUsername = false;
	let notificationSound = true;

	let detectArtifacts = true;

	let richTextInput = true;
	let promptAutocomplete = false;

	let largeTextAsFile = false;

	let landingPageMode = '';
	let chatBubble = true;
	let chatDirection: 'LTR' | 'RTL' | 'auto' = 'auto';
	let ctrlEnterToSend = false;
	let copyFormatted = false;

	let collapseCodeBlocks = false;
	let expandDetails = false;

	let imageCompression = false;
	let imageCompressionSize = {
		width: '',
		height: ''
	};

	let showEmojiInCall = false;
	let voiceInterruption = false;
	let hapticFeedback = false;

	let webSearch = null;

	let iframeSandboxAllowSameOrigin = false;
	let iframeSandboxAllowForms = false;

	const toggleExpandDetails = () => {
		expandDetails = !expandDetails;
		saveSettings({ expandDetails });
	};

	const toggleCollapseCodeBlocks = () => {
		collapseCodeBlocks = !collapseCodeBlocks;
		saveSettings({ collapseCodeBlocks });
	};

	const toggleSplitLargeChunks = async () => {
		splitLargeChunks = !splitLargeChunks;
		saveSettings({ splitLargeChunks: splitLargeChunks });
	};

	const togglePromptAutocomplete = async () => {
		promptAutocomplete = !promptAutocomplete;
		saveSettings({ promptAutocomplete: promptAutocomplete });
	};

	const togglesScrollOnBranchChange = async () => {
		scrollOnBranchChange = !scrollOnBranchChange;
		saveSettings({ scrollOnBranchChange: scrollOnBranchChange });
	};

	const toggleWidescreenMode = async () => {
		widescreenMode = !widescreenMode;
		saveSettings({ widescreenMode: widescreenMode });
	};

	const toggleChatBubble = async () => {
		chatBubble = !chatBubble;
		saveSettings({ chatBubble: chatBubble });
	};

	const toggleLandingPageMode = async () => {
		landingPageMode = landingPageMode === '' ? 'chat' : '';
		saveSettings({ landingPageMode: landingPageMode });
	};

	const toggleNotificationSound = async () => {
		notificationSound = !notificationSound;
		saveSettings({ notificationSound: notificationSound });
	};

	const toggleShowUsername = async () => {
		showUsername = !showUsername;
		saveSettings({ showUsername: showUsername });
	};

	const toggleEmojiInCall = async () => {
		showEmojiInCall = !showEmojiInCall;
		saveSettings({ showEmojiInCall: showEmojiInCall });
	};

	const toggleVoiceInterruption = async () => {
		voiceInterruption = !voiceInterruption;
		saveSettings({ voiceInterruption: voiceInterruption });
	};

	const toggleImageCompression = async () => {
		imageCompression = !imageCompression;
		saveSettings({ imageCompression });
	};

	const toggleHapticFeedback = async () => {
		hapticFeedback = !hapticFeedback;
		saveSettings({ hapticFeedback: hapticFeedback });
	};

	const toggleUserLocation = async () => {
		userLocation = !userLocation;

		if (userLocation) {
			const position = await getUserPosition().catch((error) => {
				toast.error(error.message);
				return null;
			});

			if (position) {
				await updateUserInfo(localStorage.token, { location: position });
				toast.success($i18n.t('User location successfully retrieved.'));
			} else {
				userLocation = false;
			}
		}

		saveSettings({ userLocation });
	};

	const toggleTitleAutoGenerate = async () => {
		titleAutoGenerate = !titleAutoGenerate;
		saveSettings({
			title: {
				...$settings.title,
				auto: titleAutoGenerate
			}
		});
	};

	const toggleAutoTags = async () => {
		autoTags = !autoTags;
		saveSettings({ autoTags });
	};

	const toggleDetectArtifacts = async () => {
		detectArtifacts = !detectArtifacts;
		saveSettings({ detectArtifacts });
	};

	const toggleRichTextInput = async () => {
		richTextInput = !richTextInput;
		saveSettings({ richTextInput });
	};

	const toggleLargeTextAsFile = async () => {
		largeTextAsFile = !largeTextAsFile;
		saveSettings({ largeTextAsFile });
	};

	const toggleResponseAutoCopy = async () => {
		const permission = await navigator.clipboard
			.readText()
			.then(() => {
				return 'granted';
			})
			.catch(() => {
				return '';
			});

		console.log(permission);

		if (permission === 'granted') {
			responseAutoCopy = !responseAutoCopy;
			saveSettings({ responseAutoCopy: responseAutoCopy });
		} else {
			toast.error(
				$i18n.t(
					'Clipboard write permission denied. Please check your browser settings to grant the necessary access.'
				)
			);
		}
	};

	const toggleCopyFormatted = async () => {
		copyFormatted = !copyFormatted;
		saveSettings({ copyFormatted });
	};

	const toggleChangeChatDirection = async () => {
		if (chatDirection === 'auto') {
			chatDirection = 'LTR';
		} else if (chatDirection === 'LTR') {
			chatDirection = 'RTL';
		} else if (chatDirection === 'RTL') {
			chatDirection = 'auto';
		}
		saveSettings({ chatDirection });
	};

	const togglectrlEnterToSend = async () => {
		ctrlEnterToSend = !ctrlEnterToSend;
		saveSettings({ ctrlEnterToSend });
	};

	const updateInterfaceHandler = async () => {
		saveSettings({
			models: [defaultModelId],
			imageCompressionSize: imageCompressionSize
		});
	};

	const toggleWebSearch = async () => {
		webSearch = webSearch === null ? 'always' : null;
		saveSettings({ webSearch: webSearch });
	};

	const toggleIframeSandboxAllowSameOrigin = async () => {
		iframeSandboxAllowSameOrigin = !iframeSandboxAllowSameOrigin;
		saveSettings({ iframeSandboxAllowSameOrigin });
	};

	const toggleIframeSandboxAllowForms = async () => {
		iframeSandboxAllowForms = !iframeSandboxAllowForms;
		saveSettings({ iframeSandboxAllowForms });
	};

	onMount(async () => {
		titleAutoGenerate = $settings?.title?.auto ?? true;
		autoTags = $settings.autoTags ?? true;

		detectArtifacts = $settings.detectArtifacts ?? true;
		responseAutoCopy = $settings.responseAutoCopy ?? false;

		showUsername = $settings.showUsername ?? false;

		showEmojiInCall = $settings.showEmojiInCall ?? false;
		voiceInterruption = $settings.voiceInterruption ?? false;

		richTextInput = $settings.richTextInput ?? true;
		promptAutocomplete = $settings.promptAutocomplete ?? false;
		largeTextAsFile = $settings.largeTextAsFile ?? false;
		copyFormatted = $settings.copyFormatted ?? false;

		collapseCodeBlocks = $settings.collapseCodeBlocks ?? false;
		expandDetails = $settings.expandDetails ?? false;

		landingPageMode = $settings.landingPageMode ?? '';
		chatBubble = $settings.chatBubble ?? true;
		widescreenMode = $settings.widescreenMode ?? false;
		splitLargeChunks = $settings.splitLargeChunks ?? false;
		scrollOnBranchChange = $settings.scrollOnBranchChange ?? true;
		chatDirection = $settings.chatDirection ?? 'auto';
		userLocation = $settings.userLocation ?? false;

		notificationSound = $settings.notificationSound ?? true;

		hapticFeedback = $settings.hapticFeedback ?? false;
		ctrlEnterToSend = $settings.ctrlEnterToSend ?? false;

		imageCompression = $settings.imageCompression ?? false;
		imageCompressionSize = $settings.imageCompressionSize ?? { width: '', height: '' };

		defaultModelId = $settings?.models?.at(0) ?? '';
		if ($config?.default_models) {
			defaultModelId = $config.default_models.split(',')[0];
		}

		backgroundImageUrl = $settings.backgroundImageUrl ?? null;
		webSearch = $settings.webSearch ?? null;
	});
</script>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={() => {
		updateInterfaceHandler();
		dispatch('save');
	}}
>
	<input
		bind:this={filesInputElement}
		bind:files={inputFiles}
		type="file"
		hidden
		accept="image/*"
		on:change={() => {
			let reader = new FileReader();
			reader.onload = (event) => {
				let originalImageUrl = `${event.target.result}`;

				backgroundImageUrl = originalImageUrl;
				saveSettings({ backgroundImageUrl });
			};

			if (
				inputFiles &&
				inputFiles.length > 0 &&
				['image/gif', 'image/webp', 'image/jpeg', 'image/png'].includes(inputFiles[0]['type'])
			) {
				reader.readAsDataURL(inputFiles[0]);
			} else {
				console.log(`Unsupported File Type '${inputFiles[0]['type']}'.`);
				inputFiles = null;
			}
		}}
	/>

	<div class=" space-y-3 overflow-y-scroll max-h-[28rem] lg:max-h-full">
		<div>
			<div class=" mb-1.5 text-sm font-medium">{$i18n.t('UI')}</div>

			<SettingToggle
				label={$i18n.t('Landing Page Mode')}
				text={landingPageMode === '' ? $i18n.t('Default') : $i18n.t('Chat')}
				on:click={toggleLandingPageMode}
			/>

			<SettingToggle
				label={$i18n.t('Chat Bubble UI')}
				text={chatBubble === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleChatBubble}
			/>

			{#if !$settings.chatBubble}
				<SettingToggle
					label={$i18n.t('Display the username instead of You in the Chat')}
					text={showUsername === true ? $i18n.t('On') : $i18n.t('Off')}
					on:click={toggleShowUsername}
				/>
			{/if}

			<SettingToggle
				label={$i18n.t('Widescreen Mode')}
				text={widescreenMode === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleWidescreenMode}
			/>

			<SettingToggle
				label={$i18n.t('Chat direction')}
				text={chatDirection === 'LTR'
					? $i18n.t('LTR')
					: chatDirection === 'RTL'
						? $i18n.t('RTL')
						: $i18n.t('Auto')}
				on:click={toggleChangeChatDirection}
			/>

			<SettingToggle
				label={$i18n.t('Notification Sound')}
				text={notificationSound === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleNotificationSound}
			/>

			<div class="setting-title">{$i18n.t('Chat')}</div>

			<SettingToggle
				label={$i18n.t('Title Auto-Generation')}
				text={titleAutoGenerate === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleTitleAutoGenerate}
			/>

			<SettingToggle
				label={$i18n.t('Chat Tags Auto-Generation')}
				text={autoTags === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleAutoTags}
			/>

			<SettingToggle
				label={$i18n.t('Detect Artifacts Automatically')}
				text={detectArtifacts === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleDetectArtifacts}
			/>

			<SettingToggle
				label={$i18n.t('Auto-Copy Response to Clipboard')}
				text={responseAutoCopy === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleResponseAutoCopy}
			/>

			<SettingToggle
				label={$i18n.t('Rich Text Input for Chat')}
				text={richTextInput === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleRichTextInput}
			/>

			{#if $config?.features?.enable_autocomplete_generation && richTextInput}
				<SettingToggle
					label={$i18n.t('Prompt Autocompletion')}
					text={promptAutocomplete === true ? $i18n.t('On') : $i18n.t('Off')}
					on:click={togglePromptAutocomplete}
				/>
			{/if}

			<SettingToggle
				label={$i18n.t('Paste Large Text as File')}
				text={largeTextAsFile === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleLargeTextAsFile}
			/>

			<SettingToggle
				label={$i18n.t('Copy Formatted Text')}
				text={copyFormatted === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleCopyFormatted}
			/>

			<SettingToggle
				label={$i18n.t('Always Collapse Code Blocks')}
				text={collapseCodeBlocks === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleCollapseCodeBlocks}
			/>

			<SettingToggle
				label={$i18n.t('Always Expand Details')}
				text={expandDetails === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleExpandDetails}
			/>

			<SettingToggle
				label={$i18n.t('Chat Background Image')}
				text={backgroundImageUrl !== null ? $i18n.t('Reset') : $i18n.t('Upload')}
				on:click={() => {
					if (backgroundImageUrl !== null) {
						backgroundImageUrl = null;
						saveSettings({ backgroundImageUrl });
					} else {
						filesInputElement.click();
					}
				}}
			/>

			<SettingToggle
				label={$i18n.t('Allow User Location')}
				text={userLocation === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleUserLocation}
			/>

			<SettingToggle
				label={`${$i18n.t('Haptic Feedback')} (${$i18n.t('Android')})`}
				text={hapticFeedback === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleHapticFeedback}
			/>

			<SettingToggle
				label={$i18n.t('Enter Key Behavior')}
				text={ctrlEnterToSend === true ? $i18n.t('Ctrl+Enter to Send') : $i18n.t('Enter to Send')}
				on:click={togglectrlEnterToSend}
			/>

			<SettingToggle
				label={$i18n.t('Scroll to bottom when switching between branches')}
				text={scrollOnBranchChange === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={togglesScrollOnBranchChange}
			/>

			<SettingToggle
				label={$i18n.t('Web Search in Chat')}
				text={webSearch === 'always' ? $i18n.t('Always') : $i18n.t('Default')}
				on:click={toggleWebSearch}
			/>

			<SettingToggle
				label={$i18n.t('iframe Sandbox Allow Same Origin')}
				text={iframeSandboxAllowSameOrigin === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleIframeSandboxAllowSameOrigin}
			/>

			<SettingToggle
				label={$i18n.t('iframe Sandbox Allow Forms')}
				text={iframeSandboxAllowForms === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleIframeSandboxAllowForms}
			/>

			<div class="setting-title">{$i18n.t('Voice')}</div>

			<SettingToggle
				label={$i18n.t('Allow Voice Interruption in Call')}
				text={voiceInterruption === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleVoiceInterruption}
			/>

			<SettingToggle
				label={$i18n.t('Display Emoji in Call')}
				text={showEmojiInCall === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleEmojiInCall}
			/>

			<div class="setting-title">{$i18n.t('File')}</div>

			<SettingToggle
				label={$i18n.t('Image Compression')}
				text={imageCompression === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleImageCompression}
			/>

			{#if imageCompression}
				<SettingRow label={$i18n.t('Image Max Compression Size')}>
					<div>
						<input
							bind:value={imageCompressionSize.width}
							type="number"
							class="w-20 bg-transparent outline-hidden text-center"
							min="0"
							placeholder={$i18n.t('Width')}
						/>x
						<input
							bind:value={imageCompressionSize.height}
							type="number"
							class="w-20 bg-transparent outline-hidden text-center"
							min="0"
							placeholder={$i18n.t('Height')}
						/>
					</div>
				</SettingRow>
			{/if}
		</div>
	</div>

	<div class="flex justify-end pt-3">
		<button class="btn-primary" type="submit">
			{$i18n.t('Save')}
		</button>
	</div>
</form>
