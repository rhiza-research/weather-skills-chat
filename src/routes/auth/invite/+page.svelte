<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { toast } from 'svelte-sonner';
	import { user } from '$lib/stores';
	import { getCookieSessionUser, userSignOut } from '$lib/apis/auths';
	import { acceptInvitation, getInvitation } from '$lib/apis/invitations';
	import HelpContact from '$lib/components/common/HelpContact.svelte';

	const i18n = getContext('i18n');

	let loaded = false;
	let invite = null;
	let error = '';
	let name = '';
	let password = '';
	let submitting = false;

	$: token = $page.url.searchParams.get('token') || '';
	$: signedInEmail = ($user?.email || '').toLowerCase();
	$: inviteEmail = (invite?.email || '').toLowerCase();
	$: wrongAccount = Boolean(signedInEmail && inviteEmail && signedInEmail !== inviteEmail);

	const load = async () => {
		if (!token) {
			error = "Sorry, we couldn't find that invitation. It may have been canceled";
			loaded = true;
			return;
		}
		try {
			invite = await getInvitation(token);
		} catch (err) {
			error = `${err?.detail || err}`;
			invite = null;
		}
		if (!$user?.email) {
			const session = await getCookieSessionUser();
			if (session?.email) {
				localStorage.token = session.token;
				user.set(session);
			}
		}
		loaded = true;
	};

	const signOut = async () => {
		try {
			await userSignOut();
		} catch (err) {
			// The local session still has to go so a leftover cookie cannot accept the invite.
		}
		localStorage.removeItem('token');
		user.set(undefined);
		location.reload();
	};

	const accept = async () => {
		submitting = true;
		try {
			const session = await acceptInvitation(
				token,
				localStorage.token || '',
				invite?.account_exists ? {} : { name, password }
			);
			localStorage.token = session.token;
			await user.set(session);
			await goto('/');
		} catch (err) {
			toast.error(`${err?.detail || err}`);
		}
		submitting = false;
	};

	onMount(load);
</script>

<div class="min-h-screen flex items-center justify-center px-6 bg-white dark:bg-gray-900">
	<div class="w-full max-w-md">
		{#if !loaded}
			<div class="text-sm text-gray-500">{$i18n.t('Loading...')}</div>
		{:else if error || !invite}
			<div class="text-xl font-medium dark:text-white">
				{$i18n.t("Sorry, we couldn't find that invitation. It may have been canceled")}
			</div>
			<HelpContact className="mt-6 text-sm text-gray-500" label={$i18n.t('Need help? Contact')} />
		{:else if invite.accepted}
			<div class="text-xl font-medium dark:text-white">{$i18n.t('Invitation already used')}</div>
			<p class="mt-3 text-sm text-gray-600 dark:text-gray-300">
				{$i18n.t('This invitation has already been accepted.')}
			</p>
			<HelpContact className="mt-6 text-sm text-gray-500" label={$i18n.t('Need help? Contact')} />
		{:else if invite.expired}
			<div class="text-xl font-medium dark:text-white">{$i18n.t('Invitation expired')}</div>
			<p class="mt-3 text-sm text-gray-600 dark:text-gray-300">
				{$i18n.t('Ask the person who invited you to send a new invitation.')}
			</p>
			<HelpContact className="mt-6 text-sm text-gray-500" label={$i18n.t('Need help? Contact')} />
		{:else if wrongAccount}
			<div class="text-xl font-medium dark:text-white">{$i18n.t('Signed in as someone else')}</div>
			<p class="mt-3 text-sm text-gray-600 dark:text-gray-300">
				{$i18n.t('You are signed in as {{email}}. Sign out to accept this invite for {{invite}}.', {
					email: $user.email,
					invite: invite.email
				})}
			</p>
			<button
				class="mt-6 px-4 py-2 rounded-full bg-gray-900 text-white dark:bg-white dark:text-gray-900 text-sm font-medium"
				type="button"
				on:click={signOut}
			>
				{$i18n.t('Sign out')}
			</button>
		{:else}
			<div class="text-xl font-medium dark:text-white">
				{#if invite.kind === 'organization'}
					{$i18n.t("You're invited to {{name}}", {
						name: invite.organization_name || $i18n.t('an organization')
					})}
				{:else}
					{$i18n.t("You're invited to Weather Skills")}
				{/if}
			</div>
			<p class="mt-2 text-sm text-gray-500">{invite.email}</p>

			{#if invite.account_exists && !signedInEmail}
				<p class="mt-4 text-sm text-gray-600 dark:text-gray-300">
					{$i18n.t('Sign in as this email to accept the invitation.')}
				</p>
				<a
					class="mt-6 inline-flex px-4 py-2 rounded-full bg-gray-900 text-white dark:bg-white dark:text-gray-900 text-sm font-medium"
					href={`/auth?redirect=${encodeURIComponent($page.url.pathname + $page.url.search)}`}
				>
					{$i18n.t('Sign in')}
				</a>
			{:else if invite.account_exists}
				<button
					class="mt-6 px-4 py-2 rounded-full bg-gray-900 text-white dark:bg-white dark:text-gray-900 text-sm font-medium disabled:opacity-50"
					type="button"
					disabled={submitting}
					on:click={accept}
				>
					{$i18n.t('Accept invitation')}
				</button>
			{:else}
				<form class="mt-6 flex flex-col gap-3" on:submit|preventDefault={accept}>
					<label class="text-sm">
						<span class="text-gray-600 dark:text-gray-300">{$i18n.t('Name')}</span>
						<input
							class="mt-1 w-full rounded-lg py-2 px-3 text-sm bg-gray-50 dark:bg-gray-850 outline-hidden"
							bind:value={name}
							required
						/>
					</label>
					<label class="text-sm">
						<span class="text-gray-600 dark:text-gray-300">{$i18n.t('Password')}</span>
						<input
							class="mt-1 w-full rounded-lg py-2 px-3 text-sm bg-gray-50 dark:bg-gray-850 outline-hidden"
							type="password"
							bind:value={password}
							required
						/>
					</label>
					<button
						class="mt-2 px-4 py-2 rounded-full bg-gray-900 text-white dark:bg-white dark:text-gray-900 text-sm font-medium disabled:opacity-50"
						type="submit"
						disabled={submitting}
					>
						{$i18n.t('Create account')}
					</button>
				</form>
			{/if}
		{/if}
	</div>
</div>
