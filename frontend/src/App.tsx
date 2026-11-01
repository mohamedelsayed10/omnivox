import type { ReactNode } from "react";
import { Header } from "./components/Header";
import { Rail } from "./components/Rail";
import { DemoProvider } from "./dev/DemoProvider";
import { Inspector } from "./inspector/Inspector";
import { ChatProvider } from "./state/chat";
import { LayoutProvider, useLayout } from "./state/layout";
import { SettingsProvider } from "./state/settings";
import { ToastProvider } from "./state/toast";
import { VoiceProvider } from "./state/voice";
import { ChatView } from "./views/ChatView";
import { KnowledgeView } from "./views/KnowledgeView";
import { VoiceView } from "./views/VoiceView";

// The sample-call replay only exists in dev builds; this folds away in production.
const Dev = ({ children }: { children: ReactNode }) => (import.meta.env.DEV ? <DemoProvider>{children}</DemoProvider> : <>{children}</>);

export function App() {
  return (
    <SettingsProvider>
      <ToastProvider>
        <LayoutProvider>
          <Dev>
            <ChatProvider>
              <VoiceProvider>
                <Shell />
              </VoiceProvider>
            </ChatProvider>
          </Dev>
        </LayoutProvider>
      </ToastProvider>
    </SettingsProvider>
  );
}

function Shell() {
  const { view } = useLayout();
  return (
    <div className="app">
      <a className="skip-link" href="#main" onClick={(e) => (e.preventDefault(), document.getElementById("main")?.focus())}>
        Skip to content
      </a>
      <Rail />
      <Header />
      <main id="main" className="main" tabIndex={-1} key={view}>
        {view === "voice" && <VoiceView />}
        {view === "chat" && <ChatView />}
        {view === "knowledge" && <KnowledgeView />}
      </main>
      <Inspector />
    </div>
  );
}
