import type { Meta, StoryObj } from "@storybook/react";
import { expect, userEvent, within } from "@storybook/test";
import { ReceiptChip } from "./ReceiptChip";

const meta = {
  title: "DLE/Shared/ReceiptChip",
  component: ReceiptChip,
  parameters: {
    dle: { stories: ["US-10"] },
  },
} satisfies Meta<typeof ReceiptChip>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Sealed: Story = {
  args: {
    receiptId: "7a1d2c3e-4f50-4a6b-8c7d-9e0f1a2b3c4d",
    status: "sealed",
  },
};

export const PendingAnchor: Story = {
  args: {
    receiptId: "b2e4f6a8-1c3d-4e5f-8a9b-0c1d2e3f4a5b",
    status: "pending_anchor",
  },
};

export const CopyConfirmation: Story = {
  args: {
    receiptId: "7a1d2c3e-4f50-4a6b-8c7d-9e0f1a2b3c4d",
    status: "sealed",
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    const btn = c.getByRole("button", { name: /Copy receipt ID/i });
    await userEvent.click(btn);
    await expect(c.getByText("Copied")).toBeVisible();
  },
};
