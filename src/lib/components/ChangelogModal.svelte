<script lang="ts">
	import XMarkSolid from '$lib/components/icons/XMarkSolid.svelte';
	import { getContext } from 'svelte';

	import { WEBUI_NAME, config, settings } from '$lib/stores';

	import { WEBUI_VERSION } from '$lib/constants';
	import { getChangelog } from '$lib/apis';

	import Modal from './common/Modal.svelte';
	import { updateUserSettings } from '$lib/apis/users';

	const i18n = getContext('i18n');

	export let show = false;

	let changelog = null;
	let Confetti = null;

	$: if (show && !changelog) {
		getChangelog().then((res) => {
			changelog = res;
		});
	}

	$: if (show && !Confetti) {
		import('svelte-confetti').then((module) => {
			Confetti = module.Confetti;
		});
	}
</script>

<Modal bind:show size="lg">
	<div class="px-5 pt-4 text-body">
		<div class="flex justify-between items-start">
			<div class="text-xl font-semibold">
				{$i18n.t('What’s New in')}
				{$WEBUI_NAME}
				{#if Confetti}
					<svelte:component this={Confetti} x={[-1, -0.25]} y={[0, 0.5]} />
				{/if}
			</div>
			<button
				class="self-center"
					aria-label={$i18n.t('Close')}
				on:click={() => {
					localStorage.version = $config.version;
					show = false;
				}}
			>
				<XMarkSolid className="size-5" />
			</button>
		</div>
		<div class="flex items-center mt-1">
			<div class="text-sm dark:text-gray-200">{$i18n.t('Release Notes')}</div>
			<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-200 dark:bg-gray-700" />
			<div class="text-sm dark:text-gray-200">
				v{WEBUI_VERSION}
			</div>
		</div>
	</div>

	<div class="w-full p-4 px-5 text-strong">
		<div class=" overflow-y-scroll max-h-96 scrollbar-hidden">
			<div class="mb-3">
				{#if changelog}
					{#each Object.keys(changelog) as version}
						<div class=" mb-3 pr-2">
							<div class="font-semibold text-xl mb-1 dark:text-white">
								v{version} - {changelog[version].date}
							</div>

							<hr class="border-line my-2" />

							{#each Object.keys(changelog[version]).filter((section) => section !== 'date') as section}
								<div class="">
									<div
										class="font-semibold uppercase text-xs {section === 'added'
											? 'text-white bg-blue-600'
											: section === 'fixed'
												? 'text-white bg-green-600'
												: section === 'changed'
													? 'text-white bg-yellow-600'
													: section === 'removed'
														? 'text-white bg-red-600'
														: ''}  w-fit px-3 rounded-full my-2.5"
									>
										{section}
									</div>

									<div class="my-2.5 px-1.5">
										{#each Object.keys(changelog[version][section]) as item}
											<div class="text-sm mb-2">
												<div class="font-semibold uppercase">
													{changelog[version][section][item].title}
												</div>
												<div class="mb-2 mt-1">{changelog[version][section][item].content}</div>
											</div>
										{/each}
									</div>
								</div>
							{/each}
						</div>
					{/each}
				{/if}
			</div>
		</div>
		<div class="flex justify-end pt-3 text-sm font-medium">
			<button
				on:click={async () => {
					localStorage.version = $config.version;
					await settings.set({ ...$settings, ...{ version: $config.version } });
					await updateUserSettings(localStorage.token, { ui: $settings });
					show = false;
				}}
				class="btn-primary"
			>
				<span class="relative">{$i18n.t("Okay, Let's Go!")}</span>
			</button>
		</div>
	</div>
</Modal>
