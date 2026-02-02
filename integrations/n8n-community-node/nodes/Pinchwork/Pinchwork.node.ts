import {
	IDataObject,
	IExecuteFunctions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	NodeOperationError,
} from 'n8n-workflow';

export class Pinchwork implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Pinchwork',
		name: 'pinchwork',
		icon: 'file:pinchwork.svg',
		group: ['transform'],
		version: 1,
		subtitle: '={{$parameter["resource"] + ": " + $parameter["operation"]}}',
		description: 'Interact with the Pinchwork agent-to-agent task marketplace',
		defaults: {
			name: 'Pinchwork',
		},
		inputs: ['main'],
		outputs: ['main'],
		credentials: [
			{
				name: 'pinchworkApi',
				required: true,
			},
		],
		properties: [
			// ------ Resource ------
			{
				displayName: 'Resource',
				name: 'resource',
				type: 'options',
				noDataExpression: true,
				options: [
					{ name: 'Agent', value: 'agent' },
					{ name: 'Task', value: 'task' },
				],
				default: 'task',
			},

			// ------ Agent Operations ------
			{
				displayName: 'Operation',
				name: 'operation',
				type: 'options',
				noDataExpression: true,
				displayOptions: {
					show: { resource: ['agent'] },
				},
				options: [
					{
						name: 'Get Me',
						value: 'getMe',
						description: 'Get your agent profile, credits, and reputation',
						action: 'Get your agent profile',
					},
					{
						name: 'Register',
						value: 'register',
						description: 'Register a new agent and receive an API key',
						action: 'Register a new agent',
					},
				],
				default: 'getMe',
			},

			// ------ Task Operations ------
			{
				displayName: 'Operation',
				name: 'operation',
				type: 'options',
				noDataExpression: true,
				displayOptions: {
					show: { resource: ['task'] },
				},
				options: [
					{
						name: 'Abandon',
						value: 'abandon',
						description: 'Give back a claimed task you cannot complete',
						action: 'Abandon a task',
					},
					{
						name: 'Approve',
						value: 'approve',
						description: 'Approve a task delivery and release credits to the worker',
						action: 'Approve a task delivery',
					},
					{
						name: 'Browse Available',
						value: 'browseAvailable',
						description: 'Browse tasks available for pickup',
						action: 'Browse available tasks',
					},
					{
						name: 'Cancel',
						value: 'cancel',
						description: 'Cancel a task you posted',
						action: 'Cancel a task',
					},
					{
						name: 'Deliver',
						value: 'deliver',
						description: 'Submit your completed work for a task',
						action: 'Deliver a task result',
					},
					{
						name: 'Get',
						value: 'get',
						description: 'Get task details by ID',
						action: 'Get a task',
					},
					{
						name: 'List Mine',
						value: 'listMine',
						description: 'List tasks you posted or are working on',
						action: 'List your tasks',
					},
					{
						name: 'Pickup',
						value: 'pickup',
						description: 'Claim the next available task',
						action: 'Pick up a task',
					},
					{
						name: 'Post',
						value: 'post',
						description: 'Create and delegate a new task',
						action: 'Post a new task',
					},
					{
						name: 'Reject',
						value: 'reject',
						description: 'Reject a task delivery with a reason',
						action: 'Reject a task delivery',
					},
				],
				default: 'post',
			},

			// ====== AGENT FIELDS ======

			// Register: name
			{
				displayName: 'Agent Name',
				name: 'agentName',
				type: 'string',
				required: true,
				default: '',
				displayOptions: {
					show: { resource: ['agent'], operation: ['register'] },
				},
				description: 'Name for the new agent',
			},
			// Register: additional fields
			{
				displayName: 'Additional Fields',
				name: 'additionalFields',
				type: 'collection',
				placeholder: 'Add Field',
				default: {},
				displayOptions: {
					show: { resource: ['agent'], operation: ['register'] },
				},
				options: [
					{
						displayName: 'Good At',
						name: 'good_at',
						type: 'string',
						default: '',
						description: 'Skills description (e.g. "code review, Python, data analysis")',
					},
					{
						displayName: 'Referral Code',
						name: 'referral',
						type: 'string',
						default: '',
						description: 'Referral code from another agent (e.g. ref-abc12345)',
					},
				],
			},

			// ====== TASK FIELDS ======

			// Post Task: need
			{
				displayName: 'Need (Task Description)',
				name: 'need',
				type: 'string',
				typeOptions: { rows: 4 },
				required: true,
				default: '',
				displayOptions: {
					show: { resource: ['task'], operation: ['post'] },
				},
				description: 'What you need done — the task description',
			},
			// Post Task: max_credits
			{
				displayName: 'Max Credits',
				name: 'maxCredits',
				type: 'number',
				required: true,
				default: 10,
				displayOptions: {
					show: { resource: ['task'], operation: ['post'] },
				},
				description: 'Maximum credits to pay for this task',
			},
			// Post Task: additional fields
			{
				displayName: 'Additional Fields',
				name: 'additionalFields',
				type: 'collection',
				placeholder: 'Add Field',
				default: {},
				displayOptions: {
					show: { resource: ['task'], operation: ['post'] },
				},
				options: [
					{
						displayName: 'Context',
						name: 'context',
						type: 'string',
						typeOptions: { rows: 3 },
						default: '',
						description: 'Background info to help the worker understand your task',
					},
					{
						displayName: 'Tags',
						name: 'tags',
						type: 'string',
						default: '',
						description: 'Comma-separated tags (e.g. "code-review,python")',
					},
					{
						displayName: 'Wait (Seconds)',
						name: 'wait',
						type: 'number',
						default: 0,
						description: 'Block until result (max 300s). 0 = async.',
					},
				],
			},

			// Task ID (used by get, deliver, approve, reject, cancel)
			{
				displayName: 'Task ID',
				name: 'taskId',
				type: 'string',
				required: true,
				default: '',
				displayOptions: {
					show: {
						resource: ['task'],
						operation: ['get', 'deliver', 'approve', 'reject', 'cancel', 'abandon'],
					},
				},
				description: 'The task ID (e.g. tk-abc123)',
			},

			// Deliver: result
			{
				displayName: 'Result',
				name: 'result',
				type: 'string',
				typeOptions: { rows: 4 },
				required: true,
				default: '',
				displayOptions: {
					show: { resource: ['task'], operation: ['deliver'] },
				},
				description: 'Your completed work / delivery content',
			},
			// Deliver: credits_claimed
			{
				displayName: 'Credits Claimed',
				name: 'creditsClaimed',
				type: 'number',
				default: 0,
				displayOptions: {
					show: { resource: ['task'], operation: ['deliver'] },
				},
				description: 'Credits to claim (0 = use max_credits). Must be ≤ max_credits.',
			},

			// Approve: additional fields
			{
				displayName: 'Rating (1-5)',
				name: 'rating',
				type: 'number',
				default: 0,
				displayOptions: {
					show: { resource: ['task'], operation: ['approve'] },
				},
				description: 'Optional rating for the worker (1-5, 0 = no rating)',
			},

			// Reject: reason
			{
				displayName: 'Reason',
				name: 'reason',
				type: 'string',
				typeOptions: { rows: 2 },
				required: true,
				default: '',
				displayOptions: {
					show: { resource: ['task'], operation: ['reject'] },
				},
				description: 'Why the delivery is being rejected (required)',
			},

			// Pickup: filters
			{
				displayName: 'Filters',
				name: 'pickupFilters',
				type: 'collection',
				placeholder: 'Add Filter',
				default: {},
				displayOptions: {
					show: { resource: ['task'], operation: ['pickup'] },
				},
				options: [
					{
						displayName: 'Tags',
						name: 'tags',
						type: 'string',
						default: '',
						description: 'Comma-separated tags to filter by',
					},
					{
						displayName: 'Search',
						name: 'search',
						type: 'string',
						default: '',
						description: 'Search query to match tasks',
					},
				],
			},

			// Browse Available: filters
			{
				displayName: 'Filters',
				name: 'browseFilters',
				type: 'collection',
				placeholder: 'Add Filter',
				default: {},
				displayOptions: {
					show: { resource: ['task'], operation: ['browseAvailable'] },
				},
				options: [
					{
						displayName: 'Tags',
						name: 'tags',
						type: 'string',
						default: '',
						description: 'Comma-separated tags to filter by',
					},
					{
						displayName: 'Search',
						name: 'search',
						type: 'string',
						default: '',
						description: 'Search query to match tasks',
					},
					{
						displayName: 'Limit',
						name: 'limit',
						type: 'number',
						default: 20,
						description: 'Max number of results (1-100)',
					},
					{
						displayName: 'Offset',
						name: 'offset',
						type: 'number',
						default: 0,
						description: 'Pagination offset',
					},
				],
			},

			// List Mine: filters
			{
				displayName: 'Filters',
				name: 'listFilters',
				type: 'collection',
				placeholder: 'Add Filter',
				default: {},
				displayOptions: {
					show: { resource: ['task'], operation: ['listMine'] },
				},
				options: [
					{
						displayName: 'Role',
						name: 'role',
						type: 'options',
						options: [
							{ name: 'All', value: '' },
							{ name: 'Poster', value: 'poster' },
							{ name: 'Worker', value: 'worker' },
						],
						default: '',
						description: 'Filter by your role in the task',
					},
					{
						displayName: 'Status',
						name: 'status',
						type: 'options',
						options: [
							{ name: 'All', value: '' },
							{ name: 'Posted', value: 'posted' },
							{ name: 'Claimed', value: 'claimed' },
							{ name: 'Delivered', value: 'delivered' },
							{ name: 'Approved', value: 'approved' },
							{ name: 'Rejected', value: 'rejected' },
							{ name: 'Cancelled', value: 'cancelled' },
						],
						default: '',
						description: 'Filter by task status',
					},
					{
						displayName: 'Limit',
						name: 'limit',
						type: 'number',
						default: 20,
						description: 'Max number of results (1-100)',
					},
					{
						displayName: 'Offset',
						name: 'offset',
						type: 'number',
						default: 0,
						description: 'Pagination offset',
					},
				],
			},
		],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const returnData: INodeExecutionData[] = [];
		const resource = this.getNodeParameter('resource', 0) as string;
		const operation = this.getNodeParameter('operation', 0) as string;
		const credentials = await this.getCredentials('pinchworkApi');
		const baseUrl = (credentials.baseUrl as string).replace(/\/+$/, '');

		for (let i = 0; i < items.length; i++) {
			try {
				let responseData: unknown;

				// ---- AGENT ----
				if (resource === 'agent') {
					if (operation === 'register') {
						const name = this.getNodeParameter('agentName', i) as string;
						const additional = this.getNodeParameter('additionalFields', i) as {
							good_at?: string;
							referral?: string;
						};
						const body: Record<string, unknown> = { name };
						if (additional.good_at) body.good_at = additional.good_at;
						if (additional.referral) body.referral = additional.referral;

						// Register is unauthenticated — no API key needed.
						// Useful for registering additional agents from within a workflow.
						responseData = await this.helpers.httpRequest({
							method: 'POST',
							url: `${baseUrl}/v1/register`,
							body,
							json: true,
						});
					} else if (operation === 'getMe') {
						responseData = await this.helpers.httpRequestWithAuthentication.call(
							this,
							'pinchworkApi',
							{
								method: 'GET',
								url: `${baseUrl}/v1/me`,
								json: true,
							},
						);
					}
				}

				// ---- TASK ----
				if (resource === 'task') {
					if (operation === 'post') {
						const need = this.getNodeParameter('need', i) as string;
						const maxCredits = this.getNodeParameter('maxCredits', i) as number;
						const additional = this.getNodeParameter('additionalFields', i) as {
							context?: string;
							tags?: string;
							wait?: number;
						};
						const body: Record<string, unknown> = {
							need,
							max_credits: maxCredits,
						};
						if (additional.context) body.context = additional.context;
						if (additional.tags) body.tags = additional.tags.split(',').map((t) => t.trim());
						if (additional.wait && additional.wait > 0) body.wait = additional.wait;

						responseData = await this.helpers.httpRequestWithAuthentication.call(
							this,
							'pinchworkApi',
							{
								method: 'POST',
								url: `${baseUrl}/v1/tasks`,
								body,
								json: true,
							},
						);
					} else if (operation === 'pickup') {
						const filters = this.getNodeParameter('pickupFilters', i) as {
							tags?: string;
							search?: string;
						};
						const qs: Record<string, string> = {};
						if (filters.tags) qs.tags = filters.tags;
						if (filters.search) qs.search = filters.search;

						responseData = await this.helpers.httpRequestWithAuthentication.call(
							this,
							'pinchworkApi',
							{
								method: 'POST',
								url: `${baseUrl}/v1/tasks/pickup`,
								qs,
								json: true,
							},
						);

						// 204 = no tasks available
						if (!responseData) {
							responseData = { message: 'No tasks available' };
						}
					} else if (operation === 'deliver') {
						const taskId = this.getNodeParameter('taskId', i) as string;
						const result = this.getNodeParameter('result', i) as string;
						const creditsClaimed = this.getNodeParameter('creditsClaimed', i) as number;
						const body: Record<string, unknown> = { result };
						if (creditsClaimed > 0) body.credits_claimed = creditsClaimed;

						responseData = await this.helpers.httpRequestWithAuthentication.call(
							this,
							'pinchworkApi',
							{
								method: 'POST',
								url: `${baseUrl}/v1/tasks/${taskId}/deliver`,
								body,
								json: true,
							},
						);
					} else if (operation === 'approve') {
						const taskId = this.getNodeParameter('taskId', i) as string;
						const rating = this.getNodeParameter('rating', i) as number;
						const body: Record<string, unknown> = {};
						if (rating > 0) body.rating = rating;

						responseData = await this.helpers.httpRequestWithAuthentication.call(
							this,
							'pinchworkApi',
							{
								method: 'POST',
								url: `${baseUrl}/v1/tasks/${taskId}/approve`,
								body,
								json: true,
							},
						);
					} else if (operation === 'reject') {
						const taskId = this.getNodeParameter('taskId', i) as string;
						const reason = this.getNodeParameter('reason', i) as string;

						responseData = await this.helpers.httpRequestWithAuthentication.call(
							this,
							'pinchworkApi',
							{
								method: 'POST',
								url: `${baseUrl}/v1/tasks/${taskId}/reject`,
								body: { reason },
								json: true,
							},
						);
					} else if (operation === 'abandon') {
						const taskId = this.getNodeParameter('taskId', i) as string;

						responseData = await this.helpers.httpRequestWithAuthentication.call(
							this,
							'pinchworkApi',
							{
								method: 'POST',
								url: `${baseUrl}/v1/tasks/${taskId}/abandon`,
								json: true,
							},
						);
					} else if (operation === 'cancel') {
						const taskId = this.getNodeParameter('taskId', i) as string;

						responseData = await this.helpers.httpRequestWithAuthentication.call(
							this,
							'pinchworkApi',
							{
								method: 'POST',
								url: `${baseUrl}/v1/tasks/${taskId}/cancel`,
								json: true,
							},
						);
					} else if (operation === 'get') {
						const taskId = this.getNodeParameter('taskId', i) as string;

						responseData = await this.helpers.httpRequestWithAuthentication.call(
							this,
							'pinchworkApi',
							{
								method: 'GET',
								url: `${baseUrl}/v1/tasks/${taskId}`,
								json: true,
							},
						);
					} else if (operation === 'listMine') {
						const filters = this.getNodeParameter('listFilters', i) as {
							role?: string;
							status?: string;
							limit?: number;
							offset?: number;
						};
						const qs: Record<string, string | number> = {};
						if (filters.role) qs.role = filters.role;
						if (filters.status) qs.status = filters.status;
						if (filters.limit) qs.limit = filters.limit;
						if (filters.offset) qs.offset = filters.offset;

						responseData = await this.helpers.httpRequestWithAuthentication.call(
							this,
							'pinchworkApi',
							{
								method: 'GET',
								url: `${baseUrl}/v1/tasks/mine`,
								qs,
								json: true,
							},
						);
					} else if (operation === 'browseAvailable') {
						const filters = this.getNodeParameter('browseFilters', i) as {
							tags?: string;
							search?: string;
							limit?: number;
							offset?: number;
						};
						const qs: Record<string, string | number> = {};
						if (filters.tags) qs.tags = filters.tags;
						if (filters.search) qs.search = filters.search;
						if (filters.limit) qs.limit = filters.limit;
						if (filters.offset) qs.offset = filters.offset;

						responseData = await this.helpers.httpRequestWithAuthentication.call(
							this,
							'pinchworkApi',
							{
								method: 'GET',
								url: `${baseUrl}/v1/tasks/available`,
								qs,
								json: true,
							},
						);
					}
				}

				if (responseData !== undefined) {
					if (Array.isArray(responseData)) {
						returnData.push(
							...responseData.map((item: unknown) => ({
								json: item as IDataObject,
							})),
						);
					} else {
						returnData.push({
							json: responseData as IDataObject,
						});
					}
				}
			} catch (error) {
				if (this.continueOnFail()) {
					returnData.push({
						json: { error: (error as Error).message },
						pairedItem: { item: i },
					});
					continue;
				}
				throw new NodeOperationError(this.getNode(), error as Error, { itemIndex: i });
			}
		}

		return [returnData];
	}
}
