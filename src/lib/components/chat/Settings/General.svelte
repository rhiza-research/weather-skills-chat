<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, getContext } from 'svelte';
	import { getLanguages, changeLanguage } from '$lib/i18n';

	import { settings, theme } from '$lib/stores';
	import SettingToggle from '$lib/components/common/SettingToggle.svelte';
	import SettingRow from '$lib/components/common/SettingRow.svelte';

	const i18n = getContext('i18n');

	export let saveSettings: Function;

	let themes = ['dark', 'light', 'rose-pine dark', 'rose-pine-dawn light', 'oled-dark'];
	let selectedTheme = 'system';

	let languages: Awaited<ReturnType<typeof getLanguages>> = [];
	let lang = $i18n.language;
	let notificationEnabled = false;

	const toggleNotification = async () => {
		const permission = await Notification.requestPermission();

		if (permission === 'granted') {
			notificationEnabled = !notificationEnabled;
			saveSettings({ notificationEnabled: notificationEnabled });
		} else {
			toast.error(
				$i18n.t(
					'Response notifications cannot be activated as the website permissions have been denied. Please visit your browser settings to grant the necessary access.'
				)
			);
		}
	};

	onMount(async () => {
		selectedTheme = localStorage.theme ?? 'system';

		languages = await getLanguages();

		notificationEnabled = $settings.notificationEnabled ?? false;
	});

	const applyTheme = (_theme: string) => {
		let themeToApply = _theme === 'oled-dark' ? 'dark' : _theme;

		if (_theme === 'system') {
			themeToApply = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
		}

		if (themeToApply === 'dark' && !_theme.includes('oled')) {
			document.documentElement.style.setProperty('--color-gray-800', '#333');
			document.documentElement.style.setProperty('--color-gray-850', '#262626');
			document.documentElement.style.setProperty('--color-gray-900', '#171717');
			document.documentElement.style.setProperty('--color-gray-950', '#0d0d0d');
		}

		themes
			.filter((e) => e !== themeToApply)
			.forEach((e) => {
				e.split(' ').forEach((e) => {
					document.documentElement.classList.remove(e);
				});
			});

		themeToApply.split(' ').forEach((e) => {
			document.documentElement.classList.add(e);
		});

		const metaThemeColor = document.querySelector('meta[name="theme-color"]');
		if (metaThemeColor) {
			if (_theme.includes('system')) {
				const systemTheme = window.matchMedia('(prefers-color-scheme: dark)').matches
					? 'dark'
					: 'light';
				console.log('Setting system meta theme color: ' + systemTheme);
				metaThemeColor.setAttribute('content', systemTheme === 'light' ? '#ffffff' : '#171717');
			} else {
				console.log('Setting meta theme color: ' + _theme);
				metaThemeColor.setAttribute(
					'content',
					_theme === 'dark'
						? '#171717'
						: _theme === 'oled-dark'
							? '#000000'
							: _theme === 'her'
								? '#983724'
								: '#ffffff'
				);
			}
		}

		if (typeof window !== 'undefined' && window.applyTheme) {
			window.applyTheme();
		}

		if (_theme.includes('oled')) {
			document.documentElement.style.setProperty('--color-gray-800', '#101010');
			document.documentElement.style.setProperty('--color-gray-850', '#050505');
			document.documentElement.style.setProperty('--color-gray-900', '#000000');
			document.documentElement.style.setProperty('--color-gray-950', '#000000');
			document.documentElement.classList.add('dark');
		}

		console.log(_theme);
	};

	const themeChangeHandler = (_theme: string) => {
		theme.set(_theme);
		localStorage.setItem('theme', _theme);
		applyTheme(_theme);
	};
</script>

<div class="flex flex-col h-full justify-between text-sm">
	<div class="  overflow-y-scroll max-h-[28rem] lg:max-h-full">
		<div class="">
			<div class="setting-title">{$i18n.t('WebUI Settings')}</div>

			<SettingRow label={$i18n.t('Theme')}>
				<select
					class="field-select"
					bind:value={selectedTheme}
					placeholder={$i18n.t('Select a theme')}
					on:change={() => themeChangeHandler(selectedTheme)}
				>
					<option value="system">⚙️ {$i18n.t('System')}</option>
					<option value="dark">🌑 {$i18n.t('Dark')}</option>
					<option value="oled-dark">🌃 {$i18n.t('OLED Dark')}</option>
					<option value="light">☀️ {$i18n.t('Light')}</option>
					<option value="her">🌷 Her</option>
				</select>
			</SettingRow>

			<SettingRow label={$i18n.t('Language')}>
				<select
					class="field-select"
					bind:value={lang}
					placeholder={$i18n.t('Select a language')}
					on:change={() => {
						changeLanguage(lang);
					}}
				>
					{#each languages as language}
						<option value={language['code']}>{language['title']}</option>
					{/each}
				</select>
			</SettingRow>

			<SettingToggle
				label={$i18n.t('Notifications')}
				text={notificationEnabled === true ? $i18n.t('On') : $i18n.t('Off')}
				on:click={toggleNotification}
			/>
		</div>
	</div>
</div>
