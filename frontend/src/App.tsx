import { ChatKit, useChatKit } from "@openai/chatkit-react";
import { CgClose, CgOptions } from "react-icons/cg";
import { useEffect, useState } from "react";

const CHATKIT_API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000/chatkit";
const CHATKIT_API_DOMAIN_KEY = import.meta.env.VITE_CHATKIT_API_DOMAIN_KEY ?? "domain_pk_localhost_dev";

function openReferencePage(destination: string) {
  const safeDestination = destination.trim() || "unknown";
  const url = `/#reference?filename=${encodeURIComponent(safeDestination)}`;
  window.open(url, "_blank", "noopener,noreferrer");
}

function SettingsDrawer({
  isOpen,
  onClose,
  colorScheme,
  radius,
  density,
  accentColor,
  onColorSchemeChange,
  onRadiusChange,
  onDensityChange,
  onAccentColorChange,
}: {
  isOpen: boolean;
  onClose: () => void;
  colorScheme: "light" | "dark";
  radius: "pill" | "round" | "soft" | "sharp";
  density: "compact" | "normal" | "spacious";
  accentColor: string;
  onColorSchemeChange: (value: "light" | "dark") => void;
  onRadiusChange: (value: "pill" | "round" | "soft" | "sharp") => void;
  onDensityChange: (value: "compact" | "normal" | "spacious") => void;
  onAccentColorChange: (value: string) => void;
}) {
  if (!isOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50">
      <button
        type="button"
        aria-label="Close settings"
        className="absolute inset-0 bg-slate-900/35 backdrop-blur-[1px]"
        onClick={onClose}
      />
      <aside className="absolute right-0 top-0 h-full w-[340px] border-l border-slate-200 bg-white p-5 shadow-2xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Appearance</div>
            <h2 className="text-lg font-semibold text-slate-900">Chat Settings</h2>
          </div>
          <button
            type="button"
            aria-label="Close drawer"
            onClick={onClose}
            className="rounded-lg border border-slate-200 bg-white p-2 text-slate-600 transition-colors hover:bg-slate-50 hover:text-slate-900"
          >
            <CgClose className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4">
          <label className="block">
            <div className="mb-1 text-sm font-medium text-slate-700">Accent color</div>
            <div className="mb-2 flex flex-wrap gap-2">
              {["#0689D8", "#0EA5A0", "#4F46E5", "#E11D48", "#D97706"].map((color) => (
                <button
                  key={color}
                  type="button"
                  aria-label={`Use ${color} accent color`}
                  onClick={() => onAccentColorChange(color)}
                  className={[
                    "h-7 w-7 rounded-full border-2 transition-transform hover:scale-105",
                    accentColor.toLowerCase() === color.toLowerCase() ? "border-slate-900" : "border-white",
                  ].join(" ")}
                  style={{ backgroundColor: color }}
                />
              ))}
            </div>
            <input
              type="color"
              value={accentColor}
              onChange={(e) => onAccentColorChange(e.target.value)}
              className="h-10 w-full cursor-pointer rounded-lg border border-slate-300 bg-white px-2 py-1"
            />
          </label>

          <label className="block">
            <div className="mb-1 text-sm font-medium text-slate-700">Color scheme</div>
            <select
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-[#0689D8] focus:outline-none"
              value={colorScheme}
              onChange={(e) => onColorSchemeChange(e.target.value as "light" | "dark")}
            >
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </label>

          <label className="block">
            <div className="mb-1 text-sm font-medium text-slate-700">Radius</div>
            <select
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-[#0689D8] focus:outline-none"
              value={radius}
              onChange={(e) => onRadiusChange(e.target.value as "pill" | "round" | "soft" | "sharp")}
            >
              <option value="round">Round</option>
              <option value="soft">Soft</option>
              <option value="pill">Pill</option>
              <option value="sharp">Sharp</option>
            </select>
          </label>

          <label className="block">
            <div className="mb-1 text-sm font-medium text-slate-700">Density</div>
            <select
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm focus:border-[#0689D8] focus:outline-none"
              value={density}
              onChange={(e) => onDensityChange(e.target.value as "compact" | "normal" | "spacious")}
            >
              <option value="compact">Compact</option>
              <option value="normal">Normal</option>
              <option value="spacious">Spacious</option>
            </select>
          </label>
        </div>
      </aside>
    </div>
  );
}

export default function App() {
  const [isMounted, setIsMounted] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [colorScheme, setColorScheme] = useState<"light" | "dark">("light");
  const [radius, setRadius] = useState<"pill" | "round" | "soft" | "sharp">("round");
  const [density, setDensity] = useState<"compact" | "normal" | "spacious">("normal");
  const [accentColor, setAccentColor] = useState("#0689D8");

  const chatkit = useChatKit({
    api: {
      url: CHATKIT_API_URL,
      domainKey: CHATKIT_API_DOMAIN_KEY,
    },
    theme: {
      color: {
        accent: {
          primary: accentColor,
          level: 1,
        },
      },
      colorScheme,
      radius,
      density,
    },
    widgets: {
      onAction: async (action) => {
        if (action.type !== "open_reference_page") {
          return;
        }

        const destination = action.payload?.destination;
        if (typeof destination === "string") {
          openReferencePage(destination);
        }
      },
    },
    onReady: () => console.log("ChatKit ready"),
    onError: (e) => console.error("ChatKit error:", e.error),
    onLog: (e) => console.log("ChatKit log:", e.name, e.data),
    onEffect: (e) => console.log("ChatKit effect:", e.name, e.data),
    startScreen: {
      greeting: "Welcome to Cedars-Sinai Find-a-Doc! How can we help today?",
      prompts: [
        {
          icon: "search",
          label: "Primary Care Provider",
          prompt: "Help me find a primary care provider.",
        },
        {
          icon: "search",
          label: "Cancer Treatment",
          prompt: "Help me find a cancer specialist.",
        },
        {
          icon: "search",
          label: "Knee Pain",
          prompt: "I have some pain in my knee. Help me find doctors who can help.",
        },
      ],
    },
    composer: {
      placeholder: "Describe what you're looking for...",
    },
  });

  useEffect(() => {
    setIsMounted(true);
  }, [chatkit]);

  if (!isMounted) {
    return (
      <div className="flex h-screen items-center justify-center font-sans">
        Loading ChatKit...
      </div>
    );
  }

  const pageClasses =
    colorScheme === "dark" ? "min-h-screen bg-slate-950 text-slate-100" : "min-h-screen bg-slate-50 text-slate-900";
  const headerClasses =
    colorScheme === "dark"
      ? "border-b border-slate-800 bg-slate-950/85 backdrop-blur"
      : "border-b border-slate-200 bg-white/80 backdrop-blur";
  const subtextClasses = colorScheme === "dark" ? "text-slate-400" : "text-slate-500";
  const panelClasses =
    colorScheme === "dark"
      ? "h-full overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 shadow-sm"
      : "h-full overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm";
  const initClasses =
    colorScheme === "dark"
      ? "flex h-full items-center justify-center rounded-2xl border border-slate-800 bg-slate-900 text-slate-300 shadow-sm"
      : "flex h-full items-center justify-center rounded-2xl border border-slate-200 bg-white text-slate-600 shadow-sm";

  return (
    <div className={pageClasses}>
      <header className={headerClasses}>
        <div className="mx-auto flex w-full max-w-[1080px] items-center justify-between px-4 py-3 md:px-6">
          <div>
            <div className={`text-sm font-semibold uppercase tracking-wide ${subtextClasses}`}>Support Assistant</div>
            <h1 className="text-lg font-semibold">Cedars-Sinai Find-a-Doc</h1>
          </div>
          <div className="flex items-center gap-3">
            <div className={`hidden text-sm md:block ${subtextClasses}`}>Ask a question or choose a suggested prompt.</div>
            <button
              type="button"
              onClick={() => setIsSettingsOpen(true)}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm transition-colors hover:bg-slate-50"
            >
              <CgOptions className="h-4 w-4" />
              Settings
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto h-[calc(100vh-73px)] w-full max-w-[1080px] p-4 md:p-6">
        {chatkit?.control ? (
          <div className={panelClasses}>
            <ChatKit control={chatkit.control} className="h-full w-full" />
          </div>
        ) : (
          <div className={initClasses}>
            Initializing ChatKit...
          </div>
        )}
      </main>

      <SettingsDrawer
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        colorScheme={colorScheme}
        radius={radius}
        density={density}
        accentColor={accentColor}
        onColorSchemeChange={setColorScheme}
        onRadiusChange={setRadius}
        onDensityChange={setDensity}
        onAccentColorChange={setAccentColor}
      />
    </div>
  );
}
