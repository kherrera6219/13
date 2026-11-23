import type { Meta, StoryObj } from "@storybook/react";
import { expect, userEvent, within } from "@storybook/test";
import { SAMPLE_SOURCES } from "../fixtures/phase2";
import { SourceRegistryTable } from "./SourceRegistryTable";

const meta = {
  title: "DLE/Admin/SourceRegistryTable",
  component: SourceRegistryTable,
  parameters: {
    dle: { stories: ["US-12"] },
  },
} satisfies Meta<typeof SourceRegistryTable>;

export default meta;
type Story = StoryObj<typeof meta>;

export const PopulatedWithForm: Story = {
  args: {
    sources: SAMPLE_SOURCES,
    onRefresh: () => {},
    onRegister: async () => {},
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("Valve Compliance Spec (§4.2)")).toBeVisible();
    await userEvent.type(c.getByLabelText("Title"), "Forklift Spec");
    await userEvent.type(c.getByLabelText("Document Text"), "Forklift aisle markings are mandatory.");
    await expect(c.getByRole("button", { name: "Register Source" })).toBeEnabled();
  },
};

export const Empty: Story = {
  args: {
    sources: [],
    onRefresh: () => {},
    onRegister: async () => {},
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText(/No evidence sources registered yet/i)).toBeVisible();
  },
};
