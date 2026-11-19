import type { Metadata } from "next";
import ModelSettingsPage from "./ModelSettingsPage";
import "./model-manager.css";
import "./settings.css";

export const metadata: Metadata = { title: "功能与模型｜行业新闻简报" };

export default function SettingsPage() {
  return <ModelSettingsPage />;
}
