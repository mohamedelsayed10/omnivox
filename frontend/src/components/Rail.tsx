import { AudioLines, Library, MessageSquare, type LucideIcon } from "lucide-react";
import { useLayout, type View } from "../state/layout";

const ITEMS: Array<{ view: View; label: string; icon: LucideIcon }> = [
  { view: "voice", label: "Voice", icon: AudioLines },
  { view: "chat", label: "Chat", icon: MessageSquare },
  { view: "knowledge", label: "Knowledge", icon: Library },
];

export function Logo() {
  return (
    <svg className="logo" viewBox="0 0 40 40" aria-hidden>
      <defs>
        <radialGradient id="logo-g" cx="35%" cy="30%" r="80%">
          <stop offset="0" stopColor="#a8f3ff" />
          <stop offset="0.45" stopColor="#8b7bff" />
          <stop offset="1" stopColor="#3b2fb8" />
        </radialGradient>
      </defs>
      <circle cx="20" cy="20" r="18" fill="none" stroke="#8b7bff" strokeOpacity="0.35" strokeWidth="1.5" />
      <circle cx="20" cy="20" r="11" fill="url(#logo-g)" />
    </svg>
  );
}

export function Rail() {
  const { view, navigate } = useLayout();
  return (
    <nav className="rail" aria-label="Primary">
      <a className="rail-brand" href="#/voice" aria-label="OmniVox home" onClick={() => navigate("voice")}>
        <Logo />
        <span>OmniVox</span>
      </a>
      <ul className="rail-list">
        {ITEMS.map(({ view: v, label, icon: Icon }) => (
          <li key={v}>
            <a
              href={`#/${v}`}
              className="rail-item"
              aria-current={view === v ? "page" : undefined}
              onClick={(e) => {
                e.preventDefault();
                navigate(v);
              }}
            >
              <Icon size={22} strokeWidth={1.9} aria-hidden />
              <span>{label}</span>
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
