<script lang="ts">
	import ArrowPathSolid from '$lib/components/icons/ArrowPathSolid.svelte';
	import XMarkSolid from '$lib/components/icons/XMarkSolid.svelte';
	import { toast } from 'svelte-sonner';
	import { getContext, onMount } from 'svelte';
	const i18n = getContext('i18n');

	import { models } from '$lib/stores';
	import { verifyOpenAIConnection } from '$lib/apis/openai';
	import { verifyOllamaConnection } from '$lib/apis/ollama';

	import Modal from '$lib/components/common/Modal.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Minus from '$lib/components/icons/Minus.svelte';
	import PencilSolid from '$lib/components/icons/PencilSolid.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Tags from './common/Tags.svelte';
	import { getToolServerData } from '$lib/apis';
	import { verifyToolServerConnection } from '$lib/apis/configs';
	import AccessControl from './workspace/common/AccessControl.svelte';

	export let onSubmit: Function = () => {};
	export let onDelete: Function = () => {};

	export let show = false;
	export let edit = false;

	export let direct = false;

	export let connection = null;

	let url = '';
	let path = 'openapi.json';

	let auth_type = 'bearer';
	let key = '';

	let accessControl = {};

	let enable = true;

	let loading = false;

	const verifyHandler = async () => {
		if (url === '') {
			toast.error($i18n.t('Please enter a valid URL'));
			return;
		}

		if (path === '') {
			toast.error($i18n.t('Please enter a valid path'));
			return;
		}

		if (direct) {
			const res = await getToolServerData(
				auth_type === 'bearer' ? key : localStorage.token,
				`${url}/${path}`
			).catch((err) => {
				toast.error($i18n.t('Connection failed'));
			});

			if (res) {
				toast.success($i18n.t('Connection successful'));
				console.debug('Connection successful', res);
			}
		} else {
			const res = await verifyToolServerConnection(localStorage.token, {
				url,
				path,
				auth_type,
				key,
				config: {
					enable: enable,
					access_control: accessControl
				}
			}).catch((err) => {
				toast.error($i18n.t('Connection failed'));
			});

			if (res) {
				toast.success($i18n.t('Connection successful'));
				console.debug('Connection successful', res);
			}
		}
	};

	const submitHandler = async () => {
		loading = true;

		// remove trailing slash from url
		url = url.replace(/\/$/, '');

		const connection = {
			url,
			path,
			auth_type,
			key,
			config: {
				enable: enable,
				access_control: accessControl
			}
		};

		await onSubmit(connection);

		loading = false;
		show = false;

		url = '';
		path = 'openapi.json';
		key = '';
		auth_type = 'bearer';

		enable = true;
		accessControl = null;
	};

	const init = () => {
		if (connection) {
			url = connection.url;
			path = connection?.path ?? 'openapi.json';

			auth_type = connection?.auth_type ?? 'bearer';
			key = connection?.key ?? '';

			enable = connection.config?.enable ?? true;
			accessControl = connection.config?.access_control ?? null;
		}
	};

	$: if (show) {
		init();
	}

	onMount(() => {
		init();
	});
</script>

<Modal size="sm" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-100 px-5 pt-4 pb-2">
			<h2 class="modal-title">
				{#if edit}
					{$i18n.t('Edit Connection')}
				{:else}
					{$i18n.t('Add Connection')}
				{/if}
			</h2>
			<button
				class="self-center"
					aria-label={$i18n.t('Close')}
				on:click={() => {
					show = false;
				}}
			>
				<XMarkSolid className="size-5" />
			</button>
		</div>

		<div class="flex flex-col md:flex-row w-full px-4 pb-4 md:space-x-4 dark:text-gray-200">
			<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				<form
					class="flex flex-col w-full"
					on:submit={(e) => {
						e.preventDefault();
						submitHandler();
					}}
				>
					<div class="px-1">
						<div class="flex gap-2">
							<div class="flex flex-col w-full">
								<div class="flex justify-between mb-0.5">
									<div class="text-xs text-muted">{$i18n.t('URL')}</div>
								</div>

								<div class="flex flex-1 items-center">
									<input
										class="field-bare flex-1 text-sm placeholder:text-gray-300 dark:placeholder:text-gray-700"
										type="text"
										bind:value={url}
										placeholder={$i18n.t('API Base URL')}
										autocomplete="off"
										required
									/>

									<Tooltip
										content={$i18n.t('Verify Connection')}
										className="shrink-0 flex items-center mr-1"
									>
										<button
											class="btn-ghost btn-ghost-xs"
											on:click={() => {
												verifyHandler();
											}}
											type="button"
										>
											<ArrowPathSolid className="size-4" />
										</button>
									</Tooltip>

									<Tooltip content={enable ? $i18n.t('Enabled') : $i18n.t('Disabled')}>
										<Switch bind:state={enable} />
									</Tooltip>
								</div>

								<div class="flex-1 flex items-center">
									<div class="text-sm">/</div>
									<input
										class="field-bare text-sm placeholder:text-gray-300 dark:placeholder:text-gray-700"
										type="text"
										bind:value={path}
										placeholder={$i18n.t('openapi.json Path')}
										autocomplete="off"
										required
									/>
								</div>
							</div>
						</div>

						<div class="text-xs text-muted mt-1">
							{$i18n.t(`WebUI will make requests to "{{url}}"`, {
								url: `${url}/${path}`
							})}
						</div>

						<div class="flex gap-2 mt-2">
							<div class="flex flex-col w-full">
								<div class="text-xs text-muted">{$i18n.t('Auth')}</div>

								<div class="flex gap-2">
									<div class="flex-shrink-0 self-start">
										<select
											class="w-full text-sm bg-transparent dark:bg-gray-900 placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-hidden pr-5"
											bind:value={auth_type}
										>
											<option value="bearer">Bearer</option>
											<option value="session">Session</option>
										</select>
									</div>

									<div class="flex flex-1 items-center">
										{#if auth_type === 'bearer'}
											<SensitiveInput
												className="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-hidden"
												bind:value={key}
												placeholder={$i18n.t('API Key')}
												required={false}
											/>
										{:else if auth_type === 'session'}
											<div class="text-xs text-muted self-center translate-y-[1px]">
												{$i18n.t('Forwards system user session credentials to authenticate')}
											</div>
										{/if}
									</div>
								</div>
							</div>
						</div>

						{#if !direct}
							<hr class="divider my-2.5 w-full" />

							<div class="my-2 -mx-2">
								<div class="px-3 py-2 bg-gray-50 dark:bg-gray-950 rounded-lg">
									<AccessControl bind:accessControl />
								</div>
							</div>
						{/if}
					</div>

					<div class="flex justify-end pt-3 text-sm font-medium gap-1.5">
						{#if edit}
							<button
								class="px-4 py-1.5 text-sm font-medium dark:bg-black dark:hover:bg-gray-900 dark:text-white bg-white text-black hover:bg-gray-100 transition rounded-full flex flex-row space-x-1 items-center"
								type="button"
								on:click={() => {
									onDelete();
									show = false;
								}}
							>
								{$i18n.t('Delete')}
							</button>
						{/if}

						<button
							class="px-4 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full flex flex-row space-x-1 items-center {loading
								? ' cursor-not-allowed'
								: ''}"
							type="submit"
							disabled={loading}
						>
							{$i18n.t('Save')}

							{#if loading}
								<div class="ml-2 self-center">
									<svg
										class=" size-4"
										viewBox="0 0 24 24"
										fill="currentColor"
										xmlns="http://www.w3.org/2000/svg"
										><style>
											.spinner_ajPY {
												transform-origin: center;
												animation: spinner_AtaB 0.75s infinite linear;
											}
											@keyframes spinner_AtaB {
												100% {
													transform: rotate(360deg);
												}
											}
										</style><path
											d="M12,1A11,11,0,1,0,23,12,11,11,0,0,0,12,1Zm0,19a8,8,0,1,1,8-8A8,8,0,0,1,12,20Z"
											opacity=".25"
										/><path
											d="M10.14,1.16a11,11,0,0,0-9,8.92A1.59,1.59,0,0,0,2.46,12,1.52,1.52,0,0,0,4.11,10.7a8,8,0,0,1,6.66-6.61A1.42,1.42,0,0,0,12,2.69h0A1.57,1.57,0,0,0,10.14,1.16Z"
											class="spinner_ajPY"
										/></svg
									>
								</div>
							{/if}
						</button>
					</div>
				</form>
			</div>
		</div>
	</div>
</Modal>
