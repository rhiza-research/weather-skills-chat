<script lang="ts">
	import ParamField from '$lib/components/common/ParamField.svelte';
	import SettingToggle from '$lib/components/common/SettingToggle.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { getContext, createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	const i18n = getContext('i18n');

	export let admin = false;

	export let params = {
		// Advanced
		stream_response: null, // Set stream responses for this model individually
		function_calling: null,
		seed: null,
		stop: null,
		temperature: null,
		reasoning_effort: null,
		logit_bias: null,
		frequency_penalty: null,
		repeat_last_n: null,
		mirostat: null,
		mirostat_eta: null,
		mirostat_tau: null,
		top_k: null,
		top_p: null,
		min_p: null,
		tfs_z: null,
		num_ctx: null,
		num_batch: null,
		num_keep: null,
		max_tokens: null,
		use_mmap: null,
		use_mlock: null,
		num_thread: null,
		num_gpu: null,
		template: null
	};

	let customFieldName = '';
	let customFieldValue = '';

	$: if (params) {
		dispatch('change', params);
	}
</script>

<div class=" space-y-1 text-xs pb-safe-bottom">
	<SettingToggle
		label={$i18n.t('Stream Chat Response')}
		tooltip={$i18n.t(
			'When enabled, the model will respond to each chat message in real-time, generating a response as soon as the user sends a message. This mode is useful for live chat applications, but may impact performance on slower hardware.'
		)}
		text={params.stream_response === true
			? $i18n.t('On')
			: params.stream_response === false
				? $i18n.t('Off')
				: $i18n.t('Default')}
		on:click={() => {
			params.stream_response =
				(params?.stream_response ?? null) === null ? true : params.stream_response ? false : null;
		}}
	/>

	<SettingToggle
		label={$i18n.t('Function Calling')}
		tooltip={$i18n.t(
			'Default mode works with a wider range of models by calling tools once before execution. Native mode leverages the model’s built-in tool-calling capabilities, but requires the model to inherently support this feature.'
		)}
		text={params.function_calling === 'native' ? $i18n.t('Native') : $i18n.t('Default')}
		on:click={() => {
			params.function_calling = (params?.function_calling ?? null) === null ? 'native' : null;
		}}
	/>

	<ParamField
		label={$i18n.t('Seed')}
		tooltip={$i18n.t(
			'Sets the random number seed to use for generation. Setting this to a specific number will make the model generate the same text for the same prompt.'
		)}
		bind:value={params.seed}
		start={0}
		type="number"
		min={0}
		placeholder={$i18n.t('Enter Seed')}
	/>

	<ParamField
		label={$i18n.t('Stop Sequence')}
		tooltip={$i18n.t(
			'Sets the stop sequences to use. When this pattern is encountered, the LLM will stop generating text and return. Multiple stop patterns may be set by specifying multiple separate stop parameters in a modelfile.'
		)}
		bind:value={params.stop}
		placeholder={$i18n.t('Enter stop sequence')}
	/>

	<ParamField
		label={$i18n.t('Temperature')}
		tooltip={$i18n.t(
			'The temperature of the model. Increasing the temperature will make the model answer more creatively.'
		)}
		bind:value={params.temperature}
		start={0.8}
		type="range"
		min={0}
		max={2}
		step={0.05}
	/>

	<ParamField
		label={$i18n.t('Reasoning Effort')}
		tooltip={$i18n.t(
			'Constrains effort on reasoning for reasoning models. Only applicable to reasoning models from specific providers that support reasoning effort.'
		)}
		bind:value={params.reasoning_effort}
		start="medium"
		placeholder={$i18n.t('Enter reasoning effort')}
	/>

	<ParamField
		label={$i18n.t('Logit Bias')}
		tooltip={$i18n.t(
			'Boosting or penalizing specific tokens for constrained responses. Bias values will be clamped between -100 and 100 (inclusive). (Default: none)'
		)}
		bind:value={params.logit_bias}
		placeholder={$i18n.t(
			'Enter comma-seperated "token:bias_value" pairs (example: 5432:100, 413:-100)'
		)}
	/>

	<ParamField
		label={$i18n.t('Mirostat')}
		tooltip={$i18n.t('Enable Mirostat sampling for controlling perplexity.')}
		bind:value={params.mirostat}
		start={0}
		type="range"
		min={0}
		max={2}
		step={1}
	/>

	<ParamField
		label={$i18n.t('Mirostat Eta')}
		tooltip={$i18n.t(
			'Influences how quickly the algorithm responds to feedback from the generated text. A lower learning rate will result in slower adjustments, while a higher learning rate will make the algorithm more responsive.'
		)}
		bind:value={params.mirostat_eta}
		start={0.1}
		type="range"
		min={0}
		max={1}
		step={0.05}
	/>

	<ParamField
		label={$i18n.t('Mirostat Tau')}
		tooltip={$i18n.t(
			'Controls the balance between coherence and diversity of the output. A lower value will result in more focused and coherent text.'
		)}
		bind:value={params.mirostat_tau}
		start={5.0}
		type="range"
		min={0}
		max={10}
		step={0.5}
	/>

	<ParamField
		label={$i18n.t('Top K')}
		tooltip={$i18n.t(
			'Reduces the probability of generating nonsense. A higher value (e.g. 100) will give more diverse answers, while a lower value (e.g. 10) will be more conservative.'
		)}
		bind:value={params.top_k}
		start={40}
		type="range"
		min={0}
		max={1000}
		step={0.5}
	/>

	<ParamField
		label={$i18n.t('Top P')}
		tooltip={$i18n.t(
			'Works together with top-k. A higher value (e.g., 0.95) will lead to more diverse text, while a lower value (e.g., 0.5) will generate more focused and conservative text.'
		)}
		bind:value={params.top_p}
		start={0.9}
		type="range"
		min={0}
		max={1}
		step={0.05}
	/>

	<ParamField
		label={$i18n.t('Min P')}
		tooltip={$i18n.t(
			'Alternative to the top_p, and aims to ensure a balance of quality and variety. The parameter p represents the minimum probability for a token to be considered, relative to the probability of the most likely token. For example, with p=0.05 and the most likely token having a probability of 0.9, logits with a value less than 0.045 are filtered out.'
		)}
		bind:value={params.min_p}
		start={0.0}
		type="range"
		min={0}
		max={1}
		step={0.05}
	/>

	<ParamField
		label={$i18n.t('Frequency Penalty')}
		tooltip={$i18n.t(
			'Sets a scaling bias against tokens to penalize repetitions, based on how many times they have appeared. A higher value (e.g., 1.5) will penalize repetitions more strongly, while a lower value (e.g., 0.9) will be more lenient. At 0, it is disabled.'
		)}
		bind:value={params.frequency_penalty}
		start={1.1}
		type="range"
		min={-2}
		max={2}
		step={0.05}
	/>

	<ParamField
		label={$i18n.t('Presence Penalty')}
		tooltip={$i18n.t(
			'Sets a flat bias against tokens that have appeared at least once. A higher value (e.g., 1.5) will penalize repetitions more strongly, while a lower value (e.g., 0.9) will be more lenient. At 0, it is disabled.'
		)}
		bind:value={params.presence_penalty}
		start={0.0}
		type="range"
		min={-2}
		max={2}
		step={0.05}
	/>

	<ParamField
		label={$i18n.t('Repeat Last N')}
		tooltip={$i18n.t('Sets how far back for the model to look back to prevent repetition.')}
		bind:value={params.repeat_last_n}
		start={64}
		type="range"
		min={-1}
		max={128}
		step={1}
	/>

	<ParamField
		label={$i18n.t('Tfs Z')}
		tooltip={$i18n.t(
			'Tail free sampling is used to reduce the impact of less probable tokens from the output. A higher value (e.g., 2.0) will reduce the impact more, while a value of 1.0 disables this setting.'
		)}
		bind:value={params.tfs_z}
		start={1}
		type="range"
		min={0}
		max={2}
		step={0.05}
	/>

	<ParamField
		label={$i18n.t('Tokens To Keep On Context Refresh (num_keep)')}
		tooltip={$i18n.t(
			'This option controls how many tokens are preserved when refreshing the context. For example, if set to 2, the last 2 tokens of the conversation context will be retained. Preserving context can help maintain the continuity of a conversation, but it may reduce the ability to respond to new topics.'
		)}
		bind:value={params.num_keep}
		start={24}
		type="range"
		min={-1}
		max={10240000}
		step={1}
	/>

	<ParamField
		label={$i18n.t('Max Tokens (num_predict)')}
		tooltip={$i18n.t(
			'This option sets the maximum number of tokens the model can generate in its response. Increasing this limit allows the model to provide longer answers, but it may also increase the likelihood of unhelpful or irrelevant content being generated.'
		)}
		bind:value={params.max_tokens}
		start={128}
		type="range"
		min={-2}
		max={131072}
		step={1}
	/>

	<ParamField
		label={$i18n.t('Repeat Penalty (Ollama)')}
		tooltip={$i18n.t(
			'Control the repetition of token sequences in the generated text. A higher value (e.g., 1.5) will penalize repetitions more strongly, while a lower value (e.g., 1.1) will be more lenient. At 1, it is disabled.'
		)}
		bind:value={params.repeat_penalty}
		start={1.1}
		type="range"
		min={-2}
		max={2}
		step={0.05}
	/>

	<ParamField
		label={$i18n.t('Context Length')}
		tooltip={$i18n.t('Sets the size of the context window used to generate the next token.')}
		bind:value={params.num_ctx}
		start={2048}
		type="range"
		min={-1}
		max={10240000}
		step={1}
	/>

	<ParamField
		label={$i18n.t('Batch Size (num_batch)')}
		tooltip={$i18n.t(
			'The batch size determines how many text requests are processed together at once. A higher batch size can increase the performance and speed of the model, but it also requires more memory.'
		)}
		bind:value={params.num_batch}
		start={512}
		type="range"
		min={256}
		max={8192}
		step={256}
	/>

	{#if admin}
		<ParamField
			label={$i18n.t('use_mmap (Ollama)')}
			tooltip={$i18n.t(
				'Enable Memory Mapping (mmap) to load model data. This option allows the system to use disk storage as an extension of RAM by treating disk files as if they were in RAM. This can improve model performance by allowing for faster data access. However, it may not work correctly with all systems and can consume a significant amount of disk space.'
			)}
			bind:value={params.use_mmap}
			start={true}
			type="switch"
		/>

		<ParamField
			label={$i18n.t('use_mlock (Ollama)')}
			tooltip={$i18n.t(
				"Enable Memory Locking (mlock) to prevent model data from being swapped out of RAM. This option locks the model's working set of pages into RAM, ensuring that they will not be swapped out to disk. This can help maintain performance by avoiding page faults and ensuring fast data access."
			)}
			bind:value={params.use_mlock}
			start={true}
			type="switch"
		/>

		<ParamField
			label={$i18n.t('num_thread (Ollama)')}
			tooltip={$i18n.t(
				'Set the number of worker threads used for computation. This option controls how many threads are used to process incoming requests concurrently. Increasing this value can improve performance under high concurrency workloads but may also consume more CPU resources.'
			)}
			bind:value={params.num_thread}
			start={2}
			type="range"
			min={1}
			max={256}
			step={1}
		/>

		<ParamField
			label={$i18n.t('num_gpu (Ollama)')}
			tooltip={$i18n.t(
				'Set the number of layers, which will be off-loaded to GPU. Increasing this value can significantly improve performance for models that are optimized for GPU acceleration but may also consume more power and GPU resources.'
			)}
			bind:value={params.num_gpu}
			start={0}
			type="range"
			min={0}
			max={256}
			step={1}
		/>
	{/if}
</div>
