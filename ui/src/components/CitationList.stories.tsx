import type { Meta, StoryObj } from "@storybook/react";
import { expect, userEvent, within } from "@storybook/test";
import { SAMPLE_CITATIONS } from "../fixtures/phase2";
import { CitationList } from "./CitationList";

const meta = {
  title: "DLE/Chat/CitationList",
  component: CitationList,
  parameters: {
    dle: { stories: ["US-04"] },
  },
} satisfies Meta<typeof CitationList>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Populated: Story = {
  args: { citations: SAMPLE_CITATIONS },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    const toggle = c.getByRole("button", { name: /\[1\] Valve Compliance Spec/i });
    await userEvent.click(toggle);
    await expect(c.getByText(/Dual-redundant pressure relief valves/i)).toBeVisible();
  },
};

export const Empty: Story = {
  args: { citations: [] },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText(/No citations returned/i)).toBeVisible();
  },
};
