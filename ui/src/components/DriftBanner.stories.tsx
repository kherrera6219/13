import type { Meta, StoryObj } from "@storybook/react";
import { expect, userEvent, within } from "@storybook/test";
import { DriftBanner } from "./DriftBanner";

const meta = {
  title: "DLE/Admin/DriftBanner",
  component: DriftBanner,
  parameters: {
    dle: { stories: ["US-13"] },
  },
} satisfies Meta<typeof DriftBanner>;

export default meta;
type Story = StoryObj<typeof meta>;

export const HealthyHidden: Story = {
  args: {
    driftLatch: "clear",
  },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector("[role='alert']")).toBeNull();
  },
};

export const Tripped: Story = {
  args: {
    driftLatch: "tripped",
    initialStep: "banner",
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Drift latch tripped")).toBeVisible();
    await expect(c.getByRole("button", { name: "Reset Drift Latch" })).toBeVisible();
  },
};

export const ResetConfirmationStep1: Story = {
  args: {
    driftLatch: "tripped",
    initialStep: "confirm1",
    initialArtifactId: "cal-phase6-v1",
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByLabelText(/Step 1 of 2/i)).toHaveValue("cal-phase6-v1");
    await expect(c.getByRole("button", { name: "Continue to Step 2" })).toBeEnabled();
  },
};

export const ResetConfirmationStep2: Story = {
  args: {
    driftLatch: "tripped",
    initialStep: "confirm2",
    initialArtifactId: "cal-phase6-v1",
    onResetDrift: async () => undefined,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    const confirmInput = c.getByLabelText(/Step 2 of 2/i);
    const submitBtn = c.getByRole("button", { name: "Confirm Drift Reset" });
    await expect(submitBtn).toBeDisabled();
    await userEvent.type(confirmInput, "RESET");
    await expect(submitBtn).toBeEnabled();
  },
};
