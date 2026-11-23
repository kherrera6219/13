import type { Meta, StoryObj } from "@storybook/react";
import { expect, within } from "@storybook/test";
import { ReleaseBadge } from "./ReleaseBadge";

const meta = {
  title: "DLE/Shared/ReleaseBadge",
  component: ReleaseBadge,
  parameters: {
    dle: { stories: ["US-03", "US-17"] },
  },
} satisfies Meta<typeof ReleaseBadge>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Verified: Story = {
  args: { mode: "released" },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Verified")).toBeVisible();
  },
};

export const Advisory: Story = {
  args: { mode: "released_advisory" },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Advisory")).toBeVisible();
  },
};

export const HeldForReview: Story = {
  args: { mode: "held" },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Held for review")).toBeVisible();
  },
};

export const ToolCall: Story = {
  args: { mode: "tool_call" },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Tool call")).toBeVisible();
  },
};

export const ErrorState: Story = {
  args: { mode: "error" },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Error")).toBeVisible();
  },
};
