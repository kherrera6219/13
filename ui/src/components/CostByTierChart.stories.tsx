import type { Meta, StoryObj } from "@storybook/react";
import { expect, within } from "@storybook/test";
import { COST_ONE_WEEK, COST_TIER3_SPIKE } from "../fixtures/phase5";
import { CostByTierChart } from "./CostByTierChart";

const meta = {
  title: "DLE/Admin/CostByTierChart",
  component: CostByTierChart,
  parameters: {
    dle: { stories: ["US-15"] },
  },
} satisfies Meta<typeof CostByTierChart>;

export default meta;
type Story = StoryObj<typeof meta>;

export const OneWeek: Story = {
  args: {
    days: COST_ONE_WEEK,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getAllByText("2026-11-23").length).toBeGreaterThanOrEqual(1);
    await expect(c.getAllByText("Tier 1").length).toBeGreaterThanOrEqual(2);
  },
};

export const NoData: Story = {
  args: {
    days: [],
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText(/No metered cost data recorded yet/i)).toBeVisible();
  },
};

export const Tier3Spike: Story = {
  args: {
    days: COST_TIER3_SPIKE,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Tier 3 spike")).toBeVisible();
    await expect(c.getAllByText("$0.7500").length).toBeGreaterThanOrEqual(1);
  },
};
