import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { composeStories } from "@storybook/react";
import { render } from "@testing-library/react";
import axe from "axe-core";
import type { ComponentType } from "react";
import { describe, expect, it } from "vitest";
import * as AddressGraphDrawerStories from "./components/AddressGraphDrawer.stories";
import * as ChatComposerStories from "./components/ChatComposer.stories";
import * as CitationListStories from "./components/CitationList.stories";
import * as ClaimsTableStories from "./components/ClaimsTable.stories";
import * as MessageBubbleStories from "./components/MessageBubble.stories";
import * as PersonaChipsStories from "./components/PersonaChips.stories";
import * as PersonaDrawerStories from "./components/PersonaDrawer.stories";
import * as ReceiptChipStories from "./components/ReceiptChip.stories";
import * as ReceiptViewerStories from "./components/ReceiptViewer.stories";
import * as ReleaseBadgeStories from "./components/ReleaseBadge.stories";
import * as RunSummaryCardStories from "./components/RunSummaryCard.stories";
import * as SourceRegistryTableStories from "./components/SourceRegistryTable.stories";
import * as StepTimelineStories from "./components/StepTimeline.stories";

type ComposedStory = ComponentType & {
  play?: (context: { canvasElement: HTMLElement }) => Promise<void> | void;
};

const storyGroups: Array<{ name: string; stories: Record<string, ComposedStory> }> = [
  {
    name: "ReleaseBadge",
    stories: composeStories(ReleaseBadgeStories) as unknown as Record<string, ComposedStory>,
  },
  {
    name: "ReceiptChip",
    stories: composeStories(ReceiptChipStories) as unknown as Record<string, ComposedStory>,
  },
  {
    name: "ChatComposer",
    stories: composeStories(ChatComposerStories) as unknown as Record<string, ComposedStory>,
  },
  {
    name: "MessageBubble",
    stories: composeStories(MessageBubbleStories) as unknown as Record<string, ComposedStory>,
  },
  {
    name: "CitationList",
    stories: composeStories(CitationListStories) as unknown as Record<string, ComposedStory>,
  },
  {
    name: "ClaimsTable",
    stories: composeStories(ClaimsTableStories) as unknown as Record<string, ComposedStory>,
  },
  {
    name: "ReceiptViewer",
    stories: composeStories(ReceiptViewerStories) as unknown as Record<string, ComposedStory>,
  },
  {
    name: "SourceRegistryTable",
    stories: composeStories(SourceRegistryTableStories) as unknown as Record<string, ComposedStory>,
  },
  {
    name: "AddressGraphDrawer",
    stories: composeStories(AddressGraphDrawerStories) as unknown as Record<string, ComposedStory>,
  },
  {
    name: "RunSummaryCard",
    stories: composeStories(RunSummaryCardStories) as unknown as Record<string, ComposedStory>,
  },
  {
    name: "PersonaChips",
    stories: composeStories(PersonaChipsStories) as unknown as Record<string, ComposedStory>,
  },
  {
    name: "StepTimeline",
    stories: composeStories(StepTimelineStories) as unknown as Record<string, ComposedStory>,
  },
  {
    name: "PersonaDrawer",
    stories: composeStories(PersonaDrawerStories) as unknown as Record<string, ComposedStory>,
  },
];

function srgbChannelToLinear(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}

function relativeLuminance(hex: string): number {
  const clean = hex.replace("#", "");
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return (
    0.2126 * srgbChannelToLinear(r) +
    0.7152 * srgbChannelToLinear(g) +
    0.0722 * srgbChannelToLinear(b)
  );
}

function contrastRatio(hex1: string, hex2: string): number {
  const l1 = relativeLuminance(hex1);
  const l2 = relativeLuminance(hex2);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

describe("DLE-STY tokens WCAG AA contrast", () => {
  it("meets >= 4.5:1 contrast in light and dark themes", () => {
    const css = readFileSync(resolve(process.cwd(), "src/tokens.css"), "utf-8");
    const lightBlock = css.match(/\[data-theme="light"\]\s*\{([^}]+)\}/)?.[1] ?? "";
    const darkBlock = css.match(/\[data-theme="dark"\]\s*\{([^}]+)\}/)?.[1] ?? "";

    const parseVars = (block: string) => {
      const vars: Record<string, string> = {};
      for (const m of block.matchAll(/(--dle-[a-z-]+):\s*(#[0-9A-Fa-f]{6})/g)) {
        vars[m[1]] = m[2];
      }
      return vars;
    };

    for (const vars of [parseVars(lightBlock), parseVars(darkBlock)]) {
      const textTokens = [
        "--dle-text",
        "--dle-text-muted",
        "--dle-accent",
        "--dle-released",
        "--dle-advisory",
        "--dle-held",
        "--dle-error",
      ];
      for (const fg of textTokens) {
        expect(contrastRatio(vars[fg], vars["--dle-bg"])).toBeGreaterThanOrEqual(4.5);
        expect(contrastRatio(vars[fg], vars["--dle-surface"])).toBeGreaterThanOrEqual(4.5);
      }
      expect(contrastRatio(vars["--dle-on-accent"], vars["--dle-accent"])).toBeGreaterThanOrEqual(
        4.5,
      );
    }
  });
});

describe("Storybook stories play & axe checks", () => {
  for (const { name, stories } of storyGroups) {
    for (const [storyName, Story] of Object.entries(stories)) {
      it(`${name}/${storyName} passes interactions and WCAG AA axe checks`, async () => {
        const { container } = render(<Story />);
        if (Story.play) {
          await Story.play({ canvasElement: container });
        }
        // jsdom lacks canvas rendering; token contrast is verified deterministically above.
        const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
        expect(results.violations).toEqual([]);
      });
    }
  }
});
