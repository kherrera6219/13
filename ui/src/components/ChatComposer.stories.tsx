import type { Meta, StoryObj } from "@storybook/react";
import { expect, userEvent, within } from "@storybook/test";
import { ChatComposer } from "./ChatComposer";

const meta = {
  title: "DLE/Chat/ChatComposer",
  component: ChatComposer,
  parameters: {
    dle: { stories: ["US-05"] },
  },
} satisfies Meta<typeof ChatComposer>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Empty: Story = {
  args: {},
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByRole("button", { name: "Send" })).toBeDisabled();
  },
};

export const Typing: Story = {
  args: {
    initialPrompt: "Can SKU-4429-B substitute for SKU-4429-A under policy WH-2026-Q4?",
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByRole("button", { name: "Send" })).toBeEnabled();
  },
};

export const Sending: Story = {
  args: {
    initialPrompt: "Verifying claim...",
    sending: true,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByRole("button", { name: /Sending/i })).toBeDisabled();
  },
};

export const Disabled: Story = {
  args: {
    disabled: true,
  },
};

export const WithModelPicker: Story = {
  args: {
    initialModel: "dle-13axis-strict",
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    const select = c.getByLabelText("Model") as HTMLSelectElement;
    await expect(select.value).toBe("dle-13axis-strict");
    await userEvent.selectOptions(select, "dle-13axis-advisory");
    await expect(select.value).toBe("dle-13axis-advisory");
  },
};
