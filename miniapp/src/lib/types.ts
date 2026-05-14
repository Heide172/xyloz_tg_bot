export interface UserPublic {
  id: number;
  tg_id: number;
  username: string | null;
  fullname: string | null;
}

export interface BalanceResponse {
  chat_id: number;
  balance: number;
  bank: number;
}

export interface MeResponse {
  user: UserPublic;
  balance: BalanceResponse | null;
  is_admin?: boolean;
}

export interface MarketOption {
  id: number;
  position: number;
  label: string;
  pool: number;
  share: number;
}

export interface Market {
  id: number;
  chat_id: number;
  type: 'internal' | 'polymarket' | 'manifold';
  status: 'open' | 'closed' | 'resolved' | 'cancelled';
  question: string;
  options: MarketOption[];
  total_pool: number;
  bets_count: number;
  closes_at: string;
  resolved_at: string | null;
  winning_option_id: number | null;
  external_url: string | null;
  creator_id: number | null;
  created_at: string;
}

export interface PortfolioBet {
  bet_id: number;
  market_id: number;
  question: string;
  status: string;
  option_label: string;
  amount: number;
  payout: number | null;
  refunded: boolean;
  created_at: string;
}

export interface LeaderboardEntry {
  user: UserPublic;
  balance: number;
}

export interface TxItem {
  id: number;
  amount: number;
  kind: string;
  note: string | null;
  created_at: string;
}

export interface FarmState {
  cp_balance: number;
  tap_level: number;
  auto_level: number;
  auto_rate_cps: number;
  next_tap_cost: number;
  next_auto_cost: number;
  daily_converted: number;
  daily_cap: number;
  daily_remaining: number;
  bank_balance: number;
  user_balance: number;
  lifetime_cp: number;
  cp_per_hryvnia: number;
  offline_cap_seconds: number;
}

export interface GameResult {
  game_id: number;
  game: string;
  outcome: 'win' | 'lose' | 'push' | 'blackjack' | 'active' | string;
  bet: number;
  payout: number;
  net: number;
  user_balance_after: number;
  bank_after: number;
  details: Record<string, any>;
}
