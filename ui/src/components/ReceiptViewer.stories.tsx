import type { Meta, StoryObj } from "@storybook/react";
import { expect, userEvent, within } from "@storybook/test";
import { SAMPLE_HELD_RECEIPT, SAMPLE_RECEIPT } from "../fixtures/phase2";
import { ReceiptViewer } from "./ReceiptViewer";

const meta = {
  title: "DLE/Audit/ReceiptViewer",
  component: ReceiptViewer,
  parameters: {
    dle: { stories: ["US-09", "US-10"] },
  },
} satisfies Meta<typeof ReceiptViewer>;

export default meta;
type Story = StoryObj<typeof meta>;

export const SealedRelease: Story = {
  args: { receipt: SAMPLE_RECEIPT },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("gate_passed")).toBeVisible();
    await userEvent.click(c.getByText("Raw 3.8.0 Receipt JSON"));
    await expect(c.getByText(/local-worm-merkle:chain-default/)).toBeVisible();
  },
};

export const HeldBlock: Story = {
  args: { receipt: SAMPLE_HELD_RECEIPT },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("hard_veto_block")).toBeVisible();
  },
};

export const Empty: Story = {
  args: { receipt: null },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText(/Send a governed request/i)).toBeVisible();
  },
};
