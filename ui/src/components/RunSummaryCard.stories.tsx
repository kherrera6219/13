import type { Meta, StoryObj } from "@storybook/react";
import { expect, within } from "@storybook/test";
import {
  RUN_SUMMARY_ESCALATED,
  RUN_SUMMARY_TIER1,
  RUN_SUMMARY_TIER2,
  RUN_SUMMARY_TIER3,
} from "../fixtures/phase4";
import { RunSummaryCard } from "./RunSummaryCard";

const meta = {
  title: "DLE/Run panel/RunSummaryCard",
  component: RunSummaryCard,
  parameters: {
    dle: { stories: ["US-05"] },
  },
} satisfies Meta<typeof RunSummaryCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Tier1: Story = {
  args: {
    runSummary: RUN_SUMMARY_TIER1,
    releaseMode: "released",
    terminalU: 0.912,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Tier 1")).toBeVisible();
    await expect(c.getByText("Standard")).toBeVisible();
  },
};

export const Tier2: Story = {
  args: {
    runSummary: RUN_SUMMARY_TIER2,
    releaseMode: "released_advisory",
    terminalU: 0.745,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Tier 2")).toBeVisible();
    await expect(c.getByText("1 / 2")).toBeVisible();
  },
};

export const Tier3: Story = {
  args: {
    runSummary: RUN_SUMMARY_TIER3,
    releaseMode: "released",
    terminalU: 0.964,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Tier 3")).toBeVisible();
    await expect(c.getByText("Blinded")).toBeVisible();
    await expect(c.getByText("submit_purchase_order")).toBeVisible();
  },
};

export const EscalatedTier1To2: Story = {
  args: {
    runSummary: RUN_SUMMARY_ESCALATED,
    releaseMode: "released",
    terminalU: 0.881,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Escalated")).toBeVisible();
    await expect(c.getByText("Tier 1 -> Tier 2 (Escalated)")).toBeVisible();
    await expect(c.getByText("binding_claim_missing_regulator")).toBeVisible();
  },
};
