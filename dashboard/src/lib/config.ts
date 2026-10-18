import {
  Activity,
  AudioLines,
  BookOpen,
  Bot,
  ClipboardList,
  LayoutDashboard,
  Megaphone,
  Phone,
  Plug,
  Settings,
  Users,
} from "lucide-react";
import type { Page, Row } from "./types";
export const NAV: [Page, string, typeof Activity][] = [
  ["overview", "Overview", LayoutDashboard],
  ["agents", "Agents", Bot],
  ["knowledge", "Knowledge", BookOpen],
  ["connections", "Connections", Plug],
  ["numbers", "Phone numbers", Phone],
  ["contacts", "Contacts", Users],
  ["campaigns", "Campaigns", Megaphone],
  ["calls", "Call history", AudioLines],
  ["tasks", "Staff tasks", ClipboardList],
  ["settings", "Settings", Settings],
];
export const LABELS: Record<string, string> = Object.fromEntries(
  NAV.map(([key, label]) => [key, label]),
);
export const VOICES: Record<string, string> = {
  af_bella: "Bella · American",
  af_sky: "Sky · American",
  am_adam: "Adam · American",
  am_michael: "Michael · American",
  bf_emma: "Emma · British",
  ...Object.fromEntries(
    [
      "thalia",
      "andromeda",
      "helena",
      "apollo",
      "arcas",
      "aries",
      "pandora",
      "draco",
    ].map((n) => [
      `aura-2-${n}-en`,
      `${n[0].toUpperCase() + n.slice(1)} · Aura-2`,
    ]),
  ),
};
export const DEFAULT_CONFIG: Row = {
  template: "reception",
  department: "Reception",
  language: "en",
  greeting:
    "Hello, thank you for calling {{hospital_name}}. How can I help you today?",
  instructions:
    "Be warm and concise. Ask one question at a time. Use approved hospital information. Offer a staff callback when you cannot help.",
  tone: "warm",
  stt_engine: "deepgram",
  stt_connection_id: null,
  llm_connection_id: null,
  llm_model: "",
  tts_engine: "kokoro",
  tts_connection_id: null,
  voice_id: "af_bella",
  collection_ids: [],
  tools: ["request_callback", "record_outcome", "opt_out"],
  transfer_number: "",
  emergency_instructions:
    "For urgent symptoms, tell the caller to contact their local emergency service immediately and offer to connect hospital staff. Do not claim emergency services have been dispatched.",
  max_duration_seconds: 600,
  silence_timeout_seconds: 60,
  end_pause_ms: 800,
};
