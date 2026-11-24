import type { Meta, StoryObj } from "@storybook/react";
import { expect, within } from "@storybook/test";
import {
  STEPS_ESCALATION,
  STEPS_ONE_RETRY,
  STEPS_PARKED_TOOL,
  STEPS_STRAIGHT,
  STEPS_TWO_RETRIES,
} from "../fixtures/phase4";
import { StepTimeline } from "./StepTimeline";

const meta = {
  title: "DLE/Run panel/StepTimeline",
  component: StepTimeline,
  parameters: {
    dle: { stories: ["US-06"] },
  },
} satisfies Meta<typeof StepTimeline>;

export default meta;
type Story = StoryObj<typeof meta>;

export const StraightRun: Story = {
  args: {
    steps: STEPS_STRAIGHT,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("s01_ingest")).toBeVisible();
    await expect(c.getByText("s12_seal")).toBeVisible();
  },
};

export const OneRetry: Story = {
  args: {
    steps: STEPS_ONE_RETRY,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("1 retry")).toBeVisible();
  },
};

export const TwoRetries: Story = {
  args: {
    steps: STEPS_TWO_RETRIES,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("2 retries")).toBeVisible();
    await expect(c.getByText("gate_held")).toBeVisible();
  },
};

export const Escalation: Story = {
  args: {
    steps: STEPS_ESCALATION,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("1 escalated")).toBeVisible();
    await expect(c.getByText("escalated_tier_2")).toBeVisible();
  },
};

export const ParkedOnToolCall: Story = {
  args: {
    steps: STEPS_PARKED_TOOL,
    parkedToolName: "submit_purchase_order",
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Parked on tool call")).toBeVisible();
    await expect(c.getByRole("status")).toHaveTextContent(/submit_purchase_order/);
  },
};
