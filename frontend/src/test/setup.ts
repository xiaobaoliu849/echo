import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
});

vi.mock("@lobehub/icons", async () => {
  const React = await import("react");
  const dummyComponent = (props: any) => {
    return React.createElement("span", {
      "data-testid": "lobehub-icon",
      style: { width: props.size || 18, height: props.size || 18 }
    }, "icon");
  };
  
  // Custom mock wrapper for properties like Qwen.Color
  const createMockIcon = () => {
    const fn = (props: any) => dummyComponent(props);
    fn.Color = (props: any) => dummyComponent(props);
    fn.Mono = (props: any) => dummyComponent(props);
    fn.Text = (props: any) => dummyComponent(props);
    fn.Avatar = (props: any) => dummyComponent(props);
    fn.Combine = (props: any) => dummyComponent(props);
    return fn;
  };

  return {
    Qwen: createMockIcon(),
    DeepSeek: createMockIcon(),
    Gemini: createMockIcon(),
    Google: createMockIcon(),
    VertexAI: createMockIcon(),
    Groq: createMockIcon(),
    OpenRouter: createMockIcon(),
    SiliconCloud: createMockIcon(),
    XiaomiMiMo: createMockIcon(),
    OpenAI: createMockIcon(),
    Anthropic: createMockIcon(),
    Nvidia: createMockIcon(),
    ZenMux: createMockIcon(),
    ProviderIcon: (props: any) => {
      return React.createElement("span", {
        "data-testid": `provider-icon-${props.provider}`,
        style: { width: props.size || 18, height: props.size || 18 }
      }, props.provider || "icon");
    }
  };
});

