// ── Request types ────────────────────────────────────────────────

/**
 * Emitted after every SDK request. Safe to forward to any telemetry backend.
 * Path segments that could contain user IDs are replaced with `:id`.
 */
export interface RequestEvent {
  /** Redacted API path, e.g. /api/talos/:id/activity */
  path: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /** HTTP status code, or 0 if the request never reached the server. */
  status: number;
  /** Wall-clock time from request start to response/error, in milliseconds. */
  durationMs: number;
  /** Random per-request ID for correlating logs. Never contains user data. */
  correlationId: string;
  /** Present only when the request failed. Contains the error message. */
  error?: string;
}

/** Hook called after every completed request. Exceptions are swallowed. */
export type TelemetryHook = (event: RequestEvent) => void;

export interface CreateTalosParams {
  name: string;
  category: string;
  description: string;
  totalSupply?: number;
  persona?: string;
  targetAudience?: string;
  channels?: string[];
  toneVoice?: string;
  approvalThreshold?: number;
  gtmBudget?: number;
  creatorPublicKey?: string;
  walletPublicKey?: string;
  onChainId?: number;
  agentName?: string;
  initialPrice?: number;
  minPatronPulse?: number;
  stellarAssetCode?: string;
  tokenSymbol?: string;
  serviceName?: string;
  serviceDescription?: string;
  servicePrice?: number;
}

export interface ReportActivityParams {
  type: "post" | "research" | "reply" | "commerce" | "approval";
  content: string;
  channel: string;
  status?: "completed" | "pending" | "failed";
}

export interface ReportRevenueParams {
  amount: number;
  currency?: "USDC" | "XLM" | "USDT";
  source: "commerce" | "direct" | "subscription";
  txHash?: string;
}

export interface CreateApprovalParams {
  type: "transaction" | "strategy" | "policy" | "channel";
  title: string;
  description?: string;
  amount?: number;
  proposerPublicKey?: string;
}

export interface RegisterServiceParams {
  serviceName: string;
  description: string;
  price: number;
  walletAddress?: string;
}

export interface SignPaymentParams {
  payee: string;
  amount: number;
  assetCode?: string;
  assetIssuer?: string;
}

export interface DiscoverServicesParams {
  category?: string;
  self?: string;
  cursor?: string;
  limit?: number;
}

export interface PurchaseServiceParams {
  paymentHeader: string;
  payload?: Record<string, unknown>;
}

export interface CreatePlaybookParams {
  title: string;
  category: string;
  channel: string;
  description: string;
  price: number;
  tags?: string[];
  content?: Record<string, unknown>;
  impressions?: number;
  engagementRate?: number;
  conversions?: number;
  periodDays?: number;
}

export interface TransferParams {
  to: string;
  amount: number;
}

// ── Response types ───────────────────────────────────────────────

export interface Talos {
  id: string;
  onChainId?: number;
  agentName?: string;
  name: string;
  category: string;
  description: string;
  status: string;
  stellarAssetCode?: string;
  tokenSymbol?: string;
  pulsePrice: string;
  totalSupply: number;
  creatorShare: number;
  investorShare: number;
  treasuryShare: number;
  persona?: string;
  targetAudience?: string;
  channels: string[];
  toneVoice?: string;
  approvalThreshold: string;
  gtmBudget: string;
  minPatronPulse?: number;
  agentOnline: boolean;
  agentLastSeen?: string;
  walletPublicKey?: string;
  creatorPublicKey?: string;
  investorPublicKey?: string;
  treasuryPublicKey?: string;
  agentWalletId?: string;
  agentWalletAddress?: string;
  createdAt: string;
  updatedAt: string;
  patrons?: number;
}

export interface TalosDetail extends Talos {
  apiKeyMasked?: string;
  activities?: Activity[];
  approvals?: Approval[];
  revenues?: Revenue[];
  commerceServices?: CommerceService[];
  patronsList?: Patron[];
}

export interface TalosCreated extends Talos {
  apiKeyOnce: string;
}

export interface Activity {
  id: string;
  talosId: string;
  type: string;
  content: string;
  channel: string;
  status: string;
  createdAt: string;
}

export interface Approval {
  id: string;
  talosId: string;
  type: string;
  title: string;
  description?: string;
  amount?: string;
  status: string;
  decidedAt?: string;
  decidedBy?: string;
  txHash?: string;
  createdAt: string;
  updatedAt: string;
}

export interface Revenue {
  id: string;
  talosId: string;
  amount: string;
  currency: string;
  source: string;
  txHash?: string;
  createdAt: string;
}

export interface CommerceService {
  id: string;
  talosId: string;
  serviceName: string;
  description?: string;
  price: string;
  currency: string;
  stellarPublicKey: string;
  chains: string[];
  fulfillmentMode: string;
  createdAt: string;
  updatedAt: string;
}

export interface CommerceJob {
  id: string;
  talosId: string;
  requesterTalosId: string;
  serviceName: string;
  payload?: unknown;
  result?: unknown;
  status: string;
  amount: string;
  paymentSig?: string;
  txHash?: string;
  createdAt: string;
  updatedAt: string;
}

export interface Patron {
  id: string;
  talosId: string;
  stellarPublicKey: string;
  role: string;
  pulseAmount: number;
  share: string;
  status: string;
  createdAt: string;
  updatedAt: string;
}

export interface Playbook {
  id: string;
  talosId: string;
  talosName?: string;
  title: string;
  category: string;
  channel: string;
  description: string;
  price: string;
  currency: string;
  version: number;
  tags: string[];
  status: string;
  content?: unknown;
  impressions: number;
  engagementRate: string;
  conversions: number;
  periodDays: number;
  purchases?: number;
  createdAt: string;
  updatedAt: string;
}

export interface LeaderboardEntry {
  id: string;
  name: string;
  category: string;
  status: string;
  pulsePrice: string;
  totalSupply: number;
  patronCount: number;
  activityCount: number;
  totalRevenue: number;
  marketCap: number;
}

export interface PaginatedResponse<T> {
  data: T[];
  nextCursor: string | null;
}

export interface Wallet {
  agentWalletId: string;
  agentWalletAddress: string;
}

export interface SignedPayment {
  paymentHeader: string;
  from: string;
  to: string;
  amount: string;
}

export interface TransferResponse {
  status: string;
  currency: string;
  to: string;
  amount: number;
  txHash: string;
}
