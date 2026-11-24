<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, getContext } from 'svelte';
	import { getCodeExecutionConfig, setCodeExecutionConfig } from '$lib/apis/configs';

	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Switch from '$lib/components/common/Switch.svelte';

	const i18n = getContext('i18n');

	export let saveHandler: Function;

	let config = null;

	let engines = ['pyodide', 'jupyter'];

	const submitHandler = async () => {
		const res = await setCodeExecutionConfig(localStorage.token, config);
	};

	onMount(async () => {
		const res = await getCodeExecutionConfig(localStorage.token);

		if (res) {
			config = res;
		}
	});
	import SettingRow from '$lib/components/common/SettingRow.svelte';
</script>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={async () => {
		await submitHandler();
		saveHandler();
	}}
>
	<div class=" space-y-3 overflow-y-scroll scrollbar-hidden h-full">
		{#if config}
			<div>
				<div class="mb-3">
					<h3 class="section-title">{$i18n.t('General')}</h3>

					<hr class="border-line my-2" />

					<div class="mb-2.5">
						<SettingRow label={$i18n.t('Enable Code Execution')}>
							<Switch bind:state={config.ENABLE_CODE_EXECUTION} />
						</SettingRow>
					</div>

					<div class="mb-2.5">
						<SettingRow label={$i18n.t('Code Execution Engine')}>
							<div class="flex items-center relative">
								<select
									class="field-select"
									bind:value={config.CODE_EXECUTION_ENGINE}
									placeholder={$i18n.t('Select a engine')}
									required
								>
									<option disabled selected value="">{$i18n.t('Select a engine')}</option>
									{#each engines as engine}
										<option value={engine}>{engine}</option>
									{/each}
								</select>
							</div>
						</SettingRow>

						{#if config.CODE_EXECUTION_ENGINE === 'jupyter'}
							<div class="text-muted text-xs">
								{$i18n.t(
									'Warning: Jupyter execution enables arbitrary code execution, posing severe security risks—proceed with extreme caution.'
								)}
							</div>
						{/if}
					</div>

					{#if config.CODE_EXECUTION_ENGINE === 'jupyter'}
						<div class="mb-2.5 flex flex-col gap-1.5 w-full">
							<div class="text-xs font-medium">
								{$i18n.t('Jupyter URL')}
							</div>

							<div class="flex w-full">
								<div class="flex-1">
									<input
										class="field-bare text-sm py-0.5"
										type="text"
										placeholder={$i18n.t('Enter Jupyter URL')}
										bind:value={config.CODE_EXECUTION_JUPYTER_URL}
										autocomplete="off"
									/>
								</div>
							</div>
						</div>

						<div class="mb-2.5 flex flex-col gap-1.5 w-full">
							<div class=" flex gap-2 w-full items-center justify-between">
								<div class="text-xs font-medium">
									{$i18n.t('Jupyter Auth')}
								</div>

								<div>
									<select
										class="field-select text-left"
										bind:value={config.CODE_EXECUTION_JUPYTER_AUTH}
										placeholder={$i18n.t('Select an auth method')}
									>
										<option selected value="">{$i18n.t('None')}</option>
										<option value="token">{$i18n.t('Token')}</option>
										<option value="password">{$i18n.t('Password')}</option>
									</select>
								</div>
							</div>

							{#if config.CODE_EXECUTION_JUPYTER_AUTH}
								<div class="flex w-full gap-2">
									<div class="flex-1">
										{#if config.CODE_EXECUTION_JUPYTER_AUTH === 'password'}
											<SensitiveInput
												type="text"
												placeholder={$i18n.t('Enter Jupyter Password')}
												bind:value={config.CODE_EXECUTION_JUPYTER_AUTH_PASSWORD}
												autocomplete="off"
											/>
										{:else}
											<SensitiveInput
												type="text"
												placeholder={$i18n.t('Enter Jupyter Token')}
												bind:value={config.CODE_EXECUTION_JUPYTER_AUTH_TOKEN}
												autocomplete="off"
											/>
										{/if}
									</div>
								</div>
							{/if}
						</div>

						<div class="flex gap-2 w-full items-center justify-between">
							<div class="text-xs font-medium">
								{$i18n.t('Code Execution Timeout')}
							</div>

							<div class="">
								<Tooltip content={$i18n.t('Enter timeout in seconds')}>
									<input
										class="dark:bg-gray-900 w-fit rounded-sm px-2 p-1 text-xs bg-transparent outline-hidden text-right"
										type="number"
										bind:value={config.CODE_EXECUTION_JUPYTER_TIMEOUT}
										placeholder={$i18n.t('e.g. 60')}
										autocomplete="off"
									/>
								</Tooltip>
							</div>
						</div>
					{/if}
				</div>

				<div class="mb-3">
					<h3 class="section-title">{$i18n.t('Code Interpreter')}</h3>

					<hr class="border-line my-2" />

					<div class="mb-2.5">
						<SettingRow label={$i18n.t('Enable Code Interpreter')}>
							<Switch bind:state={config.ENABLE_CODE_INTERPRETER} />
						</SettingRow>
					</div>

					{#if config.ENABLE_CODE_INTERPRETER}
						<div class="mb-2.5">
							<SettingRow label={$i18n.t('Code Interpreter Engine')}>
								<div class="flex items-center relative">
									<select
										class="field-select"
										bind:value={config.CODE_INTERPRETER_ENGINE}
										placeholder={$i18n.t('Select a engine')}
										required
									>
										<option disabled selected value="">{$i18n.t('Select a engine')}</option>
										{#each engines as engine}
											<option value={engine}>{engine}</option>
										{/each}
									</select>
								</div>
							</SettingRow>

							{#if config.CODE_INTERPRETER_ENGINE === 'jupyter'}
								<div class="text-muted text-xs">
									{$i18n.t(
										'Warning: Jupyter execution enables arbitrary code execution, posing severe security risks—proceed with extreme caution.'
									)}
								</div>
							{/if}
						</div>

						{#if config.CODE_INTERPRETER_ENGINE === 'jupyter'}
							<div class="mb-2.5 flex flex-col gap-1.5 w-full">
								<div class="text-xs font-medium">
									{$i18n.t('Jupyter URL')}
								</div>

								<div class="flex w-full">
									<div class="flex-1">
										<input
											class="field-bare text-sm py-0.5"
											type="text"
											placeholder={$i18n.t('Enter Jupyter URL')}
											bind:value={config.CODE_INTERPRETER_JUPYTER_URL}
											autocomplete="off"
										/>
									</div>
								</div>
							</div>

							<div class="mb-2.5 flex flex-col gap-1.5 w-full">
								<div class="flex gap-2 w-full items-center justify-between">
									<div class="text-xs font-medium">
										{$i18n.t('Jupyter Auth')}
									</div>

									<div>
										<select
											class="field-select text-left"
											bind:value={config.CODE_INTERPRETER_JUPYTER_AUTH}
											placeholder={$i18n.t('Select an auth method')}
										>
											<option selected value="">{$i18n.t('None')}</option>
											<option value="token">{$i18n.t('Token')}</option>
											<option value="password">{$i18n.t('Password')}</option>
										</select>
									</div>
								</div>

								{#if config.CODE_INTERPRETER_JUPYTER_AUTH}
									<div class="flex w-full gap-2">
										<div class="flex-1">
											{#if config.CODE_INTERPRETER_JUPYTER_AUTH === 'password'}
												<SensitiveInput
													type="text"
													placeholder={$i18n.t('Enter Jupyter Password')}
													bind:value={config.CODE_INTERPRETER_JUPYTER_AUTH_PASSWORD}
													autocomplete="off"
												/>
											{:else}
												<SensitiveInput
													type="text"
													placeholder={$i18n.t('Enter Jupyter Token')}
													bind:value={config.CODE_INTERPRETER_JUPYTER_AUTH_TOKEN}
													autocomplete="off"
												/>
											{/if}
										</div>
									</div>
								{/if}
							</div>

							<div class="flex gap-2 w-full items-center justify-between">
								<div class="text-xs font-medium">
									{$i18n.t('Code Execution Timeout')}
								</div>

								<div class="">
									<Tooltip content={$i18n.t('Enter timeout in seconds')}>
										<input
											class="dark:bg-gray-900 w-fit rounded-sm px-2 p-1 text-xs bg-transparent outline-hidden text-right"
											type="number"
											bind:value={config.CODE_INTERPRETER_JUPYTER_TIMEOUT}
											placeholder={$i18n.t('e.g. 60')}
											autocomplete="off"
										/>
									</Tooltip>
								</div>
							</div>
						{/if}

						<hr class="border-line my-2" />

						<div>
							<div class="py-0.5 w-full">
								<div class=" mb-2.5 text-xs font-medium">
									{$i18n.t('Code Interpreter Prompt Template')}
								</div>

								<Tooltip
									content={$i18n.t(
										'Leave empty to use the default prompt, or enter a custom prompt'
									)}
									placement="top-start"
								>
									<Textarea
										bind:value={config.CODE_INTERPRETER_PROMPT_TEMPLATE}
										placeholder={$i18n.t(
											'Leave empty to use the default prompt, or enter a custom prompt'
										)}
									/>
								</Tooltip>
							</div>
						</div>
					{/if}
				</div>
			</div>
		{/if}
	</div>
	<div class="modal-actions">
		<button
			class="btn-primary"
			type="submit"
		>
			{$i18n.t('Save')}
		</button>
	</div>
</form>
