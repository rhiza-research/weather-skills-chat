<script lang="ts">
	import DOMPurify from 'dompurify';

	import { getWebhookUrl, updateWebhookUrl } from '$lib/apis';
import { getEmailToolConfig, setEmailToolConfig, getRenderingConfig, setRenderingConfig } from '$lib/apis/configs';
	import {
		getAdminConfig,
		getLdapConfig,
		getLdapServer,
		updateAdminConfig,
		updateLdapConfig,
		updateLdapServer
	} from '$lib/apis/auths';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import { helpEmailAddress, runningReleaseLabel } from '$lib/constants';
	import { config } from '$lib/stores';
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	const i18n = getContext('i18n');

	export let saveHandler: Function;

	$: helpEmail = helpEmailAddress($config?.help_email);

	let adminConfig = null;
	let webhookUrl = '';
	let emailToolConfig = {
		EMAIL_TOOL_SMTP_HOST: '',
		EMAIL_TOOL_SMTP_PORT: 465,
		EMAIL_TOOL_SMTP_USERNAME: '',
		EMAIL_TOOL_SMTP_PASSWORD: '',
		EMAIL_TOOL_SMTP_USE_TLS: true,
		EMAIL_TOOL_FROM_EMAIL: ''
	};
	let renderingConfig = {
		RENDERING_PROMPT: ''
	};

	// LDAP
	let ENABLE_LDAP = false;
	let LDAP_SERVER = {
		label: '',
		host: '',
		port: '',
		attribute_for_mail: 'mail',
		attribute_for_username: 'uid',
		app_dn: '',
		app_dn_password: '',
		search_base: '',
		search_filters: '',
		use_tls: false,
		certificate_path: '',
		ciphers: ''
	};

	const updateLdapServerHandler = async () => {
		if (!ENABLE_LDAP) return;
		const res = await updateLdapServer(localStorage.token, LDAP_SERVER).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (res) {
			toast.success($i18n.t('LDAP server updated'));
		}
	};

	const updateHandler = async () => {
		webhookUrl = await updateWebhookUrl(localStorage.token, webhookUrl);
		const res = await updateAdminConfig(localStorage.token, adminConfig);
		const emailRes = await setEmailToolConfig(localStorage.token, emailToolConfig).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		const renderingRes = await setRenderingConfig(localStorage.token, renderingConfig).catch(
			(error) => {
				toast.error(`${error}`);
				return null;
			}
		);
		await updateLdapServerHandler();

		if (res && emailRes && renderingRes) {
			saveHandler();
		} else {
			toast.error(i18n.t('Failed to update settings'));
		}
	};

	onMount(async () => {
		await Promise.all([
			(async () => {
				adminConfig = await getAdminConfig(localStorage.token);
			})(),

			(async () => {
				webhookUrl = await getWebhookUrl(localStorage.token);
			})(),
			(async () => {
				LDAP_SERVER = await getLdapServer(localStorage.token);
			})(),
			(async () => {
				const res = await getEmailToolConfig(localStorage.token);
				if (res) {
					emailToolConfig = { ...emailToolConfig, ...res };
				}
			})(),
			(async () => {
				const res = await getRenderingConfig(localStorage.token);
				if (res) {
					renderingConfig = { ...renderingConfig, ...res };
				}
			})()
		]);

		const ldapConfig = await getLdapConfig(localStorage.token);
		ENABLE_LDAP = ldapConfig.ENABLE_LDAP;
	});
	import SettingRow from '$lib/components/common/SettingRow.svelte';
</script>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={async () => {
		updateHandler();
	}}
>
	<div class="mt-0.5 space-y-3 overflow-y-scroll scrollbar-hidden h-full">
		{#if adminConfig !== null}
			<div class="">
				<div class="mb-3">
					<h3 class="section-title">{$i18n.t('General')}</h3>

					<hr class="border-line my-2" />

					<div class="mb-2.5">
						<div class="field-label flex space-x-2 items-center">
							<div>
								{$i18n.t('Version')}
							</div>
						</div>
						<div class="flex w-full justify-between items-center">
							<div class="flex flex-col text-xs text-body">
								<Tooltip content={$config?.build_hash}>
									{runningReleaseLabel($config?.image_tag)}
								</Tooltip>
							</div>
						</div>
					</div>

					<div class="mb-2.5">
						<div class="flex w-full justify-between items-center">
							<div class="text-xs pr-2">
								<div class="">
									{$i18n.t('Help')}
								</div>
								<div class="text-xs text-muted">
									{$i18n.t('Shown to users on error screens and failed responses.')}
								</div>
							</div>

							<a
								class="flex-shrink-0 text-xs font-medium underline"
								href={`mailto:${helpEmail}`}
							>
								{helpEmail}
							</a>
						</div>
					</div>

					{#if $config?.license_metadata}
						<div class="mb-2.5">
							<div class="flex w-full justify-between items-center">
								<div class="text-xs pr-2">
									<div class="">
										{$i18n.t('License')}
									</div>

									<div class="text-muted mt-0.5">
										<span class="capitalize text-strong"
											>{$config?.license_metadata?.type}
											license</span
										>
										{$i18n.t('registered to')}
										<span class="capitalize strong"
											>{$config?.license_metadata?.organization_name}</span
										>
										for
										<span class="font-medium strong"
											>{$config?.license_metadata?.seats ?? 'Unlimited'} users.</span
										>
									</div>
									{#if $config?.license_metadata?.html}
										<div class="mt-0.5">
											{@html DOMPurify.sanitize($config?.license_metadata?.html)}
										</div>
									{/if}
								</div>
							</div>
						</div>
					{/if}
				</div>

				<div class="mb-3">
					<h3 class="section-title">{$i18n.t('Authentication')}</h3>

					<hr class="border-line my-2" />

					<SettingRow label={$i18n.t('Default User Role')}>
						<div class="flex items-center relative">
							<select
								class="field-select"
								bind:value={adminConfig.DEFAULT_USER_ROLE}
								placeholder={$i18n.t('Select a role')}
							>
								<option value="pending">{$i18n.t('pending')}</option>
								<option value="user">{$i18n.t('user')}</option>
							</select>
						</div>
					</SettingRow>

					<SettingRow label={$i18n.t('Enable New Sign Ups')}>
						<Switch bind:state={adminConfig.ENABLE_SIGNUP} />
					</SettingRow>

					<SettingRow label={$i18n.t('Enable OAuth Sign Ups')} description={$i18n.t('Allow new accounts to be created on first OAuth login.')}>
						<Switch bind:state={adminConfig.ENABLE_OAUTH_SIGNUP} />
					</SettingRow>

					<SettingRow label={$i18n.t('Merge Accounts by Email')} description={$i18n.t('Link OAuth logins to existing users with the same email.')}>
						<Switch bind:state={adminConfig.OAUTH_MERGE_ACCOUNTS_BY_EMAIL} />
					</SettingRow>

					<div class="flex w-full flex-col py-1.5">
						<div class="text-xs font-medium">
							{$i18n.t('Allowed OAuth Email Domains')}
						</div>

						<input
							class="field mt-1"
							type="text"
							placeholder={$i18n.t(
								'Enter domains separated by commas (e.g., example.com,site.org)'
							)}
							bind:value={adminConfig.OAUTH_ALLOWED_DOMAINS}
						/>

						<div class="mt-1 text-xs text-muted">
							{$i18n.t('Use * to allow any domain.')}
						</div>
					</div>

					<SettingRow label={$i18n.t('Show Admin Details in Account Pending Overlay')}>
						<Switch bind:state={adminConfig.SHOW_ADMIN_DETAILS} />
					</SettingRow>

					<SettingRow label={$i18n.t('Enable API Key')}>
						<Switch bind:state={adminConfig.ENABLE_API_KEY} />
					</SettingRow>

					{#if adminConfig?.ENABLE_API_KEY}
						<SettingRow label={$i18n.t('API Key Endpoint Restrictions')}>
							<Switch bind:state={adminConfig.ENABLE_API_KEY_ENDPOINT_RESTRICTIONS} />
						</SettingRow>

						{#if adminConfig?.ENABLE_API_KEY_ENDPOINT_RESTRICTIONS}
							<div class="flex w-full flex-col py-1.5">
								<div class=" text-xs font-medium">
									{$i18n.t('Allowed Endpoints')}
								</div>

								<input
									class="field mt-1"
									type="text"
									placeholder={`e.g.) /api/v1/chats`}
									bind:value={adminConfig.API_KEY_ALLOWED_ENDPOINTS}
								/>

								<div class="mt-2 text-xs text-muted">
									{$i18n.t(
										'Comma-separated list of endpoint paths API keys may call. Leave empty to allow all.'
									)}
								</div>
							</div>
						{/if}
					{/if}

					<div class=" mb-2.5 w-full justify-between">
						<div class="flex w-full justify-between">
							<div class=" self-center text-xs font-medium">{$i18n.t('JWT Expiration')}</div>
						</div>

						<div class="flex mt-2 space-x-2">
							<input
								class="field"
								type="text"
								placeholder={`e.g.) "30m","1h", "10d". `}
								bind:value={adminConfig.JWT_EXPIRES_IN}
							/>
						</div>

						<div class="mt-2 text-xs text-muted">
							{$i18n.t('Valid time units:')}
							<span class="text-muted font-medium"
								>{$i18n.t("'s', 'm', 'h', 'd', 'w' or '-1' for no expiration.")}</span
							>
						</div>
					</div>

					<div class=" space-y-3">
						<div class="mt-2 space-y-2">
							<div class="flex justify-between items-center text-sm">
								<div class="  font-medium">{$i18n.t('LDAP')}</div>

								<div class="mt-1">
									<Switch
										bind:state={ENABLE_LDAP}
										on:change={async () => {
											updateLdapConfig(localStorage.token, ENABLE_LDAP);
										}}
									/>
								</div>
							</div>

							{#if ENABLE_LDAP}
								<div class="flex flex-col gap-1">
									<div class="flex w-full gap-2">
										<div class="w-full">
											<div class="self-center field-label min-w-fit">
												{$i18n.t('Label')}
											</div>
											<input
												class="field"
												required
												placeholder={$i18n.t('Enter server label')}
												bind:value={LDAP_SERVER.label}
											/>
										</div>
										<div class="w-full"></div>
									</div>
									<div class="flex w-full gap-2">
										<div class="w-full">
											<div class="self-center field-label min-w-fit">
												{$i18n.t('Host')}
											</div>
											<input
												class="field"
												required
												placeholder={$i18n.t('Enter server host')}
												bind:value={LDAP_SERVER.host}
											/>
										</div>
										<div class="w-full">
											<div class="self-center field-label min-w-fit">
												{$i18n.t('Port')}
											</div>
											<Tooltip
												placement="top-start"
												content={$i18n.t('Default to 389 or 636 if TLS is enabled')}
												className="w-full"
											>
												<input
													class="field"
													type="number"
													placeholder={$i18n.t('Enter server port')}
													bind:value={LDAP_SERVER.port}
												/>
											</Tooltip>
										</div>
									</div>
									<div class="flex w-full gap-2">
										<div class="w-full">
											<div class="self-center field-label min-w-fit">
												{$i18n.t('Application DN')}
											</div>
											<Tooltip
												content={$i18n.t('The Application Account DN you bind with for search')}
												placement="top-start"
											>
												<input
													class="field"
													required
													placeholder={$i18n.t('Enter Application DN')}
													bind:value={LDAP_SERVER.app_dn}
												/>
											</Tooltip>
										</div>
										<div class="w-full">
											<div class="self-center field-label min-w-fit">
												{$i18n.t('Application DN Password')}
											</div>
											<SensitiveInput
												placeholder={$i18n.t('Enter Application DN Password')}
												bind:value={LDAP_SERVER.app_dn_password}
											/>
										</div>
									</div>
									<div class="flex w-full gap-2">
										<div class="w-full">
											<div class="self-center field-label min-w-fit">
												{$i18n.t('Attribute for Mail')}
											</div>
											<Tooltip
												content={$i18n.t(
													'The LDAP attribute that maps to the mail that users use to sign in.'
												)}
												placement="top-start"
											>
												<input
													class="field"
													required
													placeholder={$i18n.t('Example: mail')}
													bind:value={LDAP_SERVER.attribute_for_mail}
												/>
											</Tooltip>
										</div>
									</div>
									<div class="flex w-full gap-2">
										<div class="w-full">
											<div class="self-center field-label min-w-fit">
												{$i18n.t('Attribute for Username')}
											</div>
											<Tooltip
												content={$i18n.t(
													'The LDAP attribute that maps to the username that users use to sign in.'
												)}
												placement="top-start"
											>
												<input
													class="field"
													required
													placeholder={$i18n.t(
														'Example: sAMAccountName or uid or userPrincipalName'
													)}
													bind:value={LDAP_SERVER.attribute_for_username}
												/>
											</Tooltip>
										</div>
									</div>
									<div class="flex w-full gap-2">
										<div class="w-full">
											<div class="self-center field-label min-w-fit">
												{$i18n.t('Search Base')}
											</div>
											<Tooltip
												content={$i18n.t('The base to search for users')}
												placement="top-start"
											>
												<input
													class="field"
													required
													placeholder={$i18n.t('Example: ou=users,dc=foo,dc=example')}
													bind:value={LDAP_SERVER.search_base}
												/>
											</Tooltip>
										</div>
									</div>
									<div class="flex w-full gap-2">
										<div class="w-full">
											<div class="self-center field-label min-w-fit">
												{$i18n.t('Search Filters')}
											</div>
											<input
												class="field"
												placeholder={$i18n.t('Example: (&(objectClass=inetOrgPerson)(uid=%s))')}
												bind:value={LDAP_SERVER.search_filters}
											/>
										</div>
									</div>
									<div class="text-xs text-muted">
										<a
											class="text-muted font-medium underline"
											href="https://ldap.com/ldap-filters/"
											target="_blank"
										>
											{$i18n.t('Click here for filter guides.')}
										</a>
									</div>
									<div>
										<div class="flex justify-between items-center text-sm">
											<div class="  font-medium">{$i18n.t('TLS')}</div>

											<div class="mt-1">
												<Switch bind:state={LDAP_SERVER.use_tls} />
											</div>
										</div>
										{#if LDAP_SERVER.use_tls}
											<div class="flex w-full gap-2">
												<div class="w-full">
													<div class="self-center field-label min-w-fit mt-1">
														{$i18n.t('Certificate Path')}
													</div>
													<input
														class="field"
														placeholder={$i18n.t('Enter certificate path')}
														bind:value={LDAP_SERVER.certificate_path}
													/>
												</div>
											</div>
											<div class="flex w-full gap-2">
												<div class="w-full">
													<div class="self-center field-label min-w-fit">
														{$i18n.t('Ciphers')}
													</div>
													<Tooltip content={$i18n.t('Default to ALL')} placement="top-start">
														<input
															class="field"
															placeholder={$i18n.t('Example: ALL')}
															bind:value={LDAP_SERVER.ciphers}
														/>
													</Tooltip>
												</div>
												<div class="w-full"></div>
											</div>
										{/if}
									</div>
								</div>
							{/if}
						</div>
					</div>
				</div>

				<div class="mb-3">
					<h3 class="section-title">{$i18n.t('Email Tool')}</h3>

					<hr class="border-line my-2" />

					<div class="space-y-2.5">
						<div class="text-xs text-muted">
							{$i18n.t(
								'Configure SMTP for built-in email sending. Environment variables still take precedence when set.'
							)}
						</div>

						<div class="flex w-full gap-2">
							<div class="w-full">
								<div class="field-label">{$i18n.t('SMTP Host')}</div>
								<input
									class="field"
									type="text"
									placeholder={$i18n.t('smtp.example.com')}
									bind:value={emailToolConfig.EMAIL_TOOL_SMTP_HOST}
								/>
							</div>
							<div class="w-full">
								<div class="field-label">{$i18n.t('SMTP Port')}</div>
								<input
									class="field"
									type="number"
									placeholder="465"
									bind:value={emailToolConfig.EMAIL_TOOL_SMTP_PORT}
								/>
							</div>
						</div>

						<div class="flex w-full gap-2">
							<div class="w-full">
								<div class="field-label">{$i18n.t('SMTP Username')}</div>
								<input
									class="field"
									type="text"
									placeholder={$i18n.t('Enter SMTP username')}
									bind:value={emailToolConfig.EMAIL_TOOL_SMTP_USERNAME}
								/>
							</div>
							<div class="w-full">
								<div class="field-label">{$i18n.t('SMTP Password')}</div>
								<SensitiveInput
									type="text"
									placeholder={$i18n.t('Enter SMTP password')}
									bind:value={emailToolConfig.EMAIL_TOOL_SMTP_PASSWORD}
								/>
							</div>
						</div>

						<div class="flex w-full gap-2">
							<div class="w-full">
								<div class="field-label">{$i18n.t('From Email')}</div>
								<input
									class="field"
									type="text"
									placeholder={$i18n.t('no-reply@example.com')}
									bind:value={emailToolConfig.EMAIL_TOOL_FROM_EMAIL}
								/>
							</div>
							<div class="w-full flex items-end justify-between pr-2 pb-1">
								<div class="text-xs font-medium">{$i18n.t('Use TLS')}</div>
								<Switch bind:state={emailToolConfig.EMAIL_TOOL_SMTP_USE_TLS} />
							</div>
						</div>
					</div>
				</div>

				<div class="mb-3">
					<h3 class="section-title">{$i18n.t('Features')}</h3>

					<hr class="border-line my-2" />

					<SettingRow label={$i18n.t('Enable Community Sharing')}>
						<Switch bind:state={adminConfig.ENABLE_COMMUNITY_SHARING} />
					</SettingRow>

					<SettingRow label={$i18n.t('Enable Message Rating')}>
						<Switch bind:state={adminConfig.ENABLE_MESSAGE_RATING} />
					</SettingRow>

					<div class="mb-2.5 w-full justify-between">
						<div class="field-label">{$i18n.t('Rendering Prompt')}</div>
						<div class="text-xs text-muted mb-2">
							{$i18n.t(
								'Injected into every chat so the model knows responses are rendered as GitHub-flavored Markdown. Leave empty to disable.'
							)}
						</div>
						<Textarea
							bind:value={renderingConfig.RENDERING_PROMPT}
							placeholder={$i18n.t(
								'Responses will be interpreted as github markdown. Please use proper escape sequences if you would like to use markdown-specific characters but not render them as markdown'
							)}
						/>
					</div>

					<div class="mb-2.5 w-full justify-between">
						<div class="flex w-full justify-between">
							<div class=" self-center text-xs font-medium">{$i18n.t('WebUI URL')}</div>
						</div>

						<div class="flex mt-2 space-x-2">
							<input
								class="field"
								type="text"
								placeholder={`e.g.) "http://localhost:3000"`}
								bind:value={adminConfig.WEBUI_URL}
							/>
						</div>

						<div class="mt-2 text-xs text-muted">
							{$i18n.t(
								'Enter the public URL of your WebUI. This URL will be used to generate links in the notifications.'
							)}
						</div>
					</div>

					<div class=" w-full justify-between">
						<div class="flex w-full justify-between">
							<div class=" self-center text-xs font-medium">{$i18n.t('Webhook URL')}</div>
						</div>

						<div class="flex mt-2 space-x-2">
							<input
								class="field"
								type="text"
								placeholder={`https://example.com/webhook`}
								bind:value={webhookUrl}
							/>
						</div>
					</div>
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
