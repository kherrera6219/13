import type { Meta, StoryObj } from "@storybook/react";
import { expect, within } from "@storybook/test";
import { SAMPLE_GROUNDED_RUN } from "../fixtures/phase2";
import {
  advisoryRun,
  errorRun,
  heldRun,
  releasedRun,
  streamingRun,
  toolCallRun,
} from "../fixtures/runs";
import { MessageBubble } from "./MessageBubble";

const meta = {
  title: "DLE/Chat/MessageBubble",
  component: MessageBubble,
  parameters: {
    dle: { stories: ["US-03", "US-16", "US-17"] },
  },
} satisfies Meta<typeof MessageBubble>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Released: Story = {
  args: { run: releasedRun },
};

export const Advisory: Story = {
  args: { run: advisoryRun },
};

export const Held: Story = {
  args: { run: heldRun },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Held for review")).toBeVisible();
    await expect(c.getByRole("status")).toHaveTextContent(/Held:/);
  },
};

export const StreamingWithKeepalive: Story = {
  args: { run: streamingRun },
};

export const ToolCallWaiting: Story = {
  args: { run: toolCallRun },
};

export const ErrorState: Story = {
  args: { run: errorRun },
};

export const GroundedWithCitations: Story = {
  args: {
    run: SAMPLE_GROUNDED_RUN,
    selected: true,
    onSelectReceipt: () => {},
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText(/Evidence Citations \(2\)/)).toBeVisible();
    await expect(c.getByRole("button", { name: "Inspecting" })).toBeVisible();
  },
};
