export type Envelope<T> = {
  code: number;
  message: string;
  data: T;
  trace_id?: string;
};

export type LoginData = {
  accessToken: string;
  tokenType: string;
  expiresIn: number;
  userId: number;
  roleCode: string;
  dataScope: number;
};

export type ProfileSource = {
  field: string;
  refs: string[];
  confidence: number | null;
};

export type ProfileData = {
  customerId: number;
  version: number;
  sections: Record<string, unknown>;
  sources: ProfileSource[];
};

export type ProfileActionResult = {
  profileId?: number;
  version?: number;
  status: string;
};

export type TagCatalogItem = {
  tagId: number;
  code: string;
  name: string;
  category: string | null;
  measurableRule: string | null;
  maxPerCustomer: number;
  sortOrder: number | null;
  sopName: string | null;
  sopVersion: number;
};

export type CustomerTagItem = {
  tagId: number;
  code: string;
  name: string;
  category: string | null;
  source: number | null;
  appliedAt: string | null;
};

export type TagRecommendItem = {
  action: string;
  tagId: number;
  tagCode: string;
  tagName: string;
  reason: string | null;
  confidence: number | null;
  evidenceRefs: string[];
  sopSummary: string | null;
};

export type ScheduleTaskItem = {
  taskId: number;
  customerId: number;
  customerNameMasked: string | null;
  type: number;
  title: string;
  calendarTitle: string | null;
  dueAt: string | null;
  priority: number | null;
  status: number;
  wechatCalendarId: string | null;
};

export type TodayTasks = {
  date: string;
  list: ScheduleTaskItem[];
  overdueCnt: number;
};

export type ParseCandidate = {
  rawTime: string;
  parsedAt: string;
  task: string;
  priority: string;
  confidence: number;
  sourceRefs: string[];
};

export type SuggestDone = {
  scenarioTags: string[];
  profileVersion: number;
  latencyMs: number;
  eventId: number;
};
