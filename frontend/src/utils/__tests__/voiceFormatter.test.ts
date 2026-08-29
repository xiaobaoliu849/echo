import { describe, expect, it } from "vitest";
import type { VoiceInfo } from "../../api";
import { formatVoiceLabel } from "../voiceFormatter";

const tZh = (zh: string, _en: string) => zh;
const tEn = (_zh: string, en: string) => en;

describe("voiceFormatter", () => {
  it("formats Edge neural voice name, gender and locale in Chinese", () => {
    const voice: VoiceInfo = {
      name: "zh-CN-XiaoxiaoNeural",
      short_name: "zh-CN-XiaoxiaoNeural",
      gender: "Female",
      locale: "zh-CN",
    };

    const label = formatVoiceLabel(voice, tZh);
    expect(label).toBe("Xiaoxiao (女) - 中文 (中国大陆)");
  });

  it("formats Edge neural voice name, gender and locale in English", () => {
    const voice: VoiceInfo = {
      name: "en-US-JennyNeural",
      short_name: "en-US-JennyNeural",
      gender: "Female",
      locale: "en-US",
    };

    const label = formatVoiceLabel(voice, tEn);
    expect(label).toBe("Jenny (Female) - English (US)");
  });

  it("formats male voice and strip pinyin in parenthesis", () => {
    const voice: VoiceInfo = {
      name: "龙安风悦 (longanfengyue)",
      short_name: "龙安风悦 (longanfengyue)",
      gender: "Male",
      locale: "zh-CN",
    };

    const label = formatVoiceLabel(voice, tZh);
    expect(label).toBe("龙安风悦 (男) - 中文 (中国大陆)");
  });

  it("handles custom and neutral genders", () => {
    const customVoice: VoiceInfo = {
      name: "MyClonedVoice",
      short_name: "MyClonedVoice",
      gender: "Custom",
      locale: "zh-CN",
    };
    expect(formatVoiceLabel(customVoice, tZh)).toBe("MyClonedVoice (自定义) - 中文 (中国大陆)");
    expect(formatVoiceLabel(customVoice, tEn)).toBe("MyClonedVoice (Custom) - Chinese (Mainland)");

    const neutralVoice: VoiceInfo = {
      name: "RoboBot",
      short_name: "RoboBot",
      gender: "Neutral",
      locale: "en-GB",
    };
    expect(formatVoiceLabel(neutralVoice, tEn)).toBe("RoboBot (Neutral) - English (UK)");
  });

  it("handles various international locales", () => {
    const jpVoice: VoiceInfo = { name: "Nanami", short_name: "Nanami", gender: "Female", locale: "ja-JP" };
    expect(formatVoiceLabel(jpVoice, tZh)).toBe("Nanami (女) - 日语 (日本)");
    expect(formatVoiceLabel(jpVoice, tEn)).toBe("Nanami (Female) - Japanese (Japan)");

    const frVoice: VoiceInfo = { name: "Henri", short_name: "Henri", gender: "Male", locale: "fr-FR" };
    expect(formatVoiceLabel(frVoice, tZh)).toBe("Henri (男) - 法语 (法国)");
    expect(formatVoiceLabel(frVoice, tEn)).toBe("Henri (Male) - French (France)");

    const deVoice: VoiceInfo = { name: "Katja", short_name: "Katja", gender: "Female", locale: "de-DE" };
    expect(formatVoiceLabel(deVoice, tEn)).toBe("Katja (Female) - German (Germany)");
  });

  it("handles unknown or empty locales and genders gracefully", () => {
    const rawVoice: VoiceInfo = {
      name: "UnknownSpeaker",
      short_name: "UnknownSpeaker",
      gender: "",
      locale: "xx-YY",
    };
    const label = formatVoiceLabel(rawVoice, tZh);
    expect(label).toBe("UnknownSpeaker - xx-YY");

    const noLocaleVoice = {
      name: "SimpleName",
      short_name: "SimpleName",
      gender: "",
      locale: "",
    } as VoiceInfo;
    expect(formatVoiceLabel(noLocaleVoice, tZh)).toBe("SimpleName");
  });
});
