import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Globe } from "lucide-react";
import { cn } from "@/lib/utils";

const languages = [
  { code: "en", name: "English" },
  { code: "ar", name: "العربية (Arabic)" },
];

interface LanguageSelectorProps {
  value: string;
  onChange: (value: string) => void;
  triggerClassName?: string;
  iconClassName?: string;
}

export function LanguageSelector({ value, onChange, triggerClassName, iconClassName }: LanguageSelectorProps) {
  const selectedLang = languages.find((l) => l.code === value);

  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger
        className={cn("w-[140px] gap-2", triggerClassName)}
        data-testid="select-language"
      >
        <Globe className={cn("h-4 w-4 text-muted-foreground", iconClassName)} />
        <SelectValue placeholder="Language">
          {selectedLang?.name || "Language"}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {languages.map((lang) => (
          <SelectItem
            key={lang.code}
            value={lang.code}
            data-testid={`select-language-${lang.code}`}
          >
            <span className="flex items-center gap-2">
              <span className="text-xs font-medium text-muted-foreground uppercase w-6">
                {lang.code}
              </span>
              <span>{lang.name}</span>
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export { languages };
