import type { Meta, StoryObj } from "@storybook/react";
import { expect, within } from "@storybook/test";
import { ExportDialog } from "./ExportDialog";

const meta = {
  title: "DLE/Audit/ExportDialog",
  component: ExportDialog,
  parameters: {
    dle: { stories: ["US-11"] },
  },
} satisfies Meta<typeof ExportDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

export const DateRangePicker: Story = {
  args: {
    onExport: async () => undefined,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByLabelText(/From \(UTC ISO-8601\)/i)).toBeVisible();
    await expect(c.getByRole("button", { name: "Export Receipt Bundle" })).toBeEnabled();
  },
};

export const BuildingBundle: Story = {
  args: {
    initialState: "building",
    onExport: async () => undefined,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByRole("status")).toHaveTextContent(/Building signed Merkle bundle/);
    await expect(c.getByRole("button", { name: /Building bundle/i })).toBeDisabled();
  },
};

export const Done: Story = {
  args: {
    initialState: "done",
    onExport: async () => undefined,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByRole("status")).toHaveTextContent(/Receipt bundle exported/);
  },
};

export const Failure: Story = {
  args: {
    initialState: "error",
    initialError: "Admin key required to export signed receipt bundles.",
    onExport: async () => undefined,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByRole("alert")).toHaveTextContent(/Admin key required/);
  },
};
