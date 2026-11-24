import type { Meta, StoryObj } from "@storybook/react";
import { expect, userEvent, within } from "@storybook/test";
import { type ComponentProps, useState } from "react";
import {
  PERSONAS_ALL_FOUR,
  PERSONAS_BLINDED,
  PERSONAS_SCHOLAR_ONLY,
  PERSONAS_SCHOLAR_PRACTITIONER,
} from "../fixtures/phase4";
import { PersonaChips } from "./PersonaChips";

function InteractiveAllFour(args: ComponentProps<typeof PersonaChips>) {
  const [selectedAxis, setSelectedAxis] = useState<number | null>(args.selectedRoleAxis);
  return (
    <PersonaChips
      personas={args.personas}
      selectedRoleAxis={selectedAxis}
      onSelectPersona={(axis) => setSelectedAxis(axis)}
    />
  );
}

const meta = {
  title: "DLE/Run panel/PersonaChips",
  component: PersonaChips,
  parameters: {
    dle: { stories: ["US-05", "US-08"] },
  },
} satisfies Meta<typeof PersonaChips>;

export default meta;
type Story = StoryObj<typeof meta>;

export const ScholarOnly: Story = {
  args: {
    personas: PERSONAS_SCHOLAR_ONLY,
    selectedRoleAxis: 8,
    onSelectPersona: () => undefined,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("1 active")).toBeVisible();
    await expect(c.getByRole("button", { name: /Scholar/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  },
};

export const ScholarAndPractitioner: Story = {
  args: {
    personas: PERSONAS_SCHOLAR_PRACTITIONER,
    selectedRoleAxis: 8,
    onSelectPersona: () => undefined,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("2 active")).toBeVisible();
    await expect(c.getByRole("button", { name: /Practitioner/i })).toBeVisible();
  },
};

export const AllFour: Story = {
  args: {
    personas: PERSONAS_ALL_FOUR,
    selectedRoleAxis: 8,
    onSelectPersona: () => undefined,
  },
  render: (args) => <InteractiveAllFour {...args} />,
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getByText("4 active")).toBeVisible();
    const regulatorBtn = c.getByRole("button", { name: /Regulator/i });
    await userEvent.click(regulatorBtn);
    await expect(regulatorBtn).toHaveAttribute("aria-pressed", "true");
    await expect(c.getByText("1 objection")).toBeVisible();
  },
};

export const BlindedMode: Story = {
  args: {
    personas: PERSONAS_BLINDED,
    selectedRoleAxis: 10,
    onSelectPersona: () => undefined,
  },
  play: async ({ canvasElement }) => {
    const c = within(canvasElement);
    await expect(c.getAllByText("Blinded").length).toBeGreaterThanOrEqual(2);
    await expect(c.getAllByText("Falsification").length).toBeGreaterThanOrEqual(1);
  },
};
