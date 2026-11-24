import type { Meta, StoryObj } from "@storybook/react";
import { expect, within } from "@storybook/test";
import { FLAGS_EMPTY, FLAGS_POPULATED } from "../fixtures/phase5";
import { FunctionFlagsEditor } from "./FunctionFlagsEditor";

const meta = {
  title: "DLE/Admin/FunctionFlagsEditor",
  component: FunctionFlagsEditor,
  parameters: {
    dle: { stories: ["US-14"] },
  },
} satisfies Meta<typeof FunctionFlagsEditor>;

export default meta;
type Story = StoryObj<typeof meta>;

export const NoFlags: Story = {
  args: {
    flags: FLAGS_EMPTY,
    onSave: async () => undefined,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("0 flagged")).toBeVisible();
    await expect(c.getByText(/No consequential functions flagged/i)).toBeVisible();
  },
};

export const ConsequentialFlagSet: Story = {
  args: {
    flags: FLAGS_POPULATED,
    onSave: async () => undefined,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("2 flagged")).toBeVisible();
    await expect(c.getByText("submit_purchase_order")).toBeVisible();
  },
};

export const SaveError: Story = {
  args: {
    flags: FLAGS_POPULATED,
    error: "Invalid function identifier: hyphens are not allowed.",
    onSave: async () => undefined,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByRole("alert")).toHaveTextContent(/Invalid function identifier/);
  },
};
