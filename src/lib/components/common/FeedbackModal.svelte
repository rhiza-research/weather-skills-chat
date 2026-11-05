<script lang="ts">
  import { getContext } from "svelte";
  import { toast } from "svelte-sonner";

  import { sendFeedback } from "$lib/apis/users";
  import { helpEmailAddress } from "$lib/constants";
  import { chatId, config, feedbackDraft, user } from "$lib/stores";
  import Modal from "$lib/components/common/Modal.svelte";

  const i18n = getContext("i18n");

  let show = false;
  let sent = false;
  let loading = false;
  let subject = "";
  let description = "";
  let openedAt = new Date();
  let chat: string | null = null;

  $: if ($feedbackDraft !== null) {
    description = $feedbackDraft;
    feedbackDraft.set(null);
    subject = "";
    sent = false;
    openedAt = new Date();
    chat = $chatId && $chatId !== "local" ? $chatId : null;
    show = true;
  }

  $: helpEmail = helpEmailAddress($config?.help_email);
  $: emailOff = $config?.features?.enable_feedback_email === false;
  $: chatLink = chat ? `${window.location.origin}/c/${chat}` : "";
  $: details = [
    `${$i18n.t("Time")}: ${openedAt.toLocaleString()}`,
    `${$i18n.t("From")}: ${$user?.name ?? ""} (${$user?.email ?? ""})`,
    ...(chatLink ? [`${$i18n.t("Chat")}: ${chatLink}`] : []),
  ];
  $: mailtoHref = `mailto:${helpEmail}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(
    `${details.join("\n")}\n\n${description}`,
  )}`;

  const submitHandler = async () => {
    if (!subject.trim() || !description.trim()) {
      toast.error($i18n.t("Please add a subject and describe the problem."));
      return;
    }
    loading = true;
    try {
      await sendFeedback(localStorage.token, {
        subject: subject.trim(),
        description: description.trim(),
        chat_id: chat,
      });
      sent = true;
    } catch (error: any) {
      toast.error(error?.detail ?? `${error}`);
    }
    loading = false;
  };
</script>

<Modal size="sm" bind:show>
  <div>
    <div class=" flex justify-between dark:text-gray-300 px-5 py-4">
      <div class=" text-lg font-medium self-center">
        {$i18n.t("Send feedback")}
      </div>
      <button
        class="self-center"
        aria-label={$i18n.t("Close")}
        on:click={() => {
          show = false;
        }}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          class="w-5 h-5"
        >
          <path
            d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
          />
        </svg>
      </button>
    </div>
    <hr class="border-gray-100 dark:border-gray-850" />

    <div class="flex flex-col w-full p-5 dark:text-gray-200">
      {#if sent}
        <div class="text-base" role="status">
          {$i18n.t("Thank you for your feedback!")}
        </div>
        <div class="flex justify-end pt-4">
          <button
            class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full"
            type="button"
            on:click={() => {
              show = false;
            }}
          >
            {$i18n.t("Close")}
          </button>
        </div>
      {:else}
        <form
          class="flex flex-col w-full"
          on:submit|preventDefault={submitHandler}
        >
          <div
            class="text-xs text-gray-500 mb-3 flex flex-col gap-0.5 break-all"
          >
            {#each details as line}
              <div>{line}</div>
            {/each}
          </div>

          <label class="flex flex-col w-full">
            <span class=" mb-0.5 text-xs text-gray-500"
              >{$i18n.t("Subject")}</span
            >
            <input
              class="w-full text-sm bg-transparent outline-hidden"
              type="text"
              maxlength="200"
              bind:value={subject}
              placeholder={$i18n.t("e.g. Forecast plot did not load")}
            />
          </label>

          <label class="flex flex-col w-full mt-3">
            <span class=" mb-0.5 text-xs text-gray-500"
              >{$i18n.t("What happened?")}</span
            >
            <textarea
              class="w-full text-sm bg-transparent outline-hidden resize-none"
              rows="6"
              maxlength="5000"
              bind:value={description}
              placeholder={$i18n.t("Describe the problem")}
            />
          </label>

          {#if emailOff}
            <div class="text-xs text-gray-600 dark:text-gray-400 mt-3">
              {$i18n.t(
                "This server can't send email, so open this message in your email app and send it to {{email}}.",
                { email: helpEmail },
              )}
            </div>
          {/if}

          <div class="flex justify-end pt-4">
            {#if emailOff}
              <a
                class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full"
                href={mailtoHref}
              >
                {$i18n.t("Open in email app")}
              </a>
            {:else}
              <button
                class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full disabled:opacity-50"
                type="submit"
                disabled={loading}
              >
                {$i18n.t("Send")}
              </button>
            {/if}
          </div>
        </form>
      {/if}
    </div>
  </div>
</Modal>
