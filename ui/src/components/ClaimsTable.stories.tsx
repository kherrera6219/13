import type { Meta, StoryObj } from "@storybook/react";
import { expect, within } from "@storybook/test";
import { SAMPLE_CLAIMS } from "../fixtures/phase2";
import { ClaimsTable } from "./ClaimsTable";

const meta = {
  title: "DLE/Run panel/ClaimsTable",
  component: ClaimsTable,
  parameters: {
    dle: { stories: ["US-07"] },
  },
} satisfies Meta<typeof ClaimsTable>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WeakestFirstDefault: Story = {
  args: { claims: SAMPLE_CLAIMS },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    const rows = c.getAllByRole("row");
    await expect(rows[1]).toHaveTextContent(/Sealed lot inspection tags/i);
    await expect(rows[1]).toHaveTextContent("0.58");
    await expect(rows[2]).toHaveTextContent("0.94");
  },
};

export const Empty: Story = {
  args: { claims: [] },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText(/No extracted claims/i)).toBeVisible();
  },
};
