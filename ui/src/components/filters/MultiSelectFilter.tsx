import { ChevronDown, Search } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { MultiSelectValue } from "@/types/filters";

interface MultiSelectFilterProps {
  options: string[];
  value: MultiSelectValue;
  onChange: (value: MultiSelectValue) => void;
  error?: string;
  showSelectAll?: boolean;
  searchable?: boolean;
}

export const MultiSelectFilter: React.FC<MultiSelectFilterProps> = ({
  options,
  value,
  onChange,
  error,
  showSelectAll = true,
  searchable = true,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");

  const filteredOptions = searchable
    ? options.filter(option =>
        option.toLowerCase().includes(searchTerm.toLowerCase())
      )
    : options;

  const handleSelectAll = () => {
    onChange({ codes: options });
  };

  const handleSelectNone = () => {
    onChange({ codes: [] });
  };

  const handleToggleOption = (option: string) => {
    const newCodes = value.codes.includes(option)
      ? value.codes.filter(code => code !== option)
      : [...value.codes, option];
    onChange({ codes: newCodes });
  };

  const getDisplayText = () => {
    if (value.codes.length === 0) return "Select options";
    if (value.codes.length <= 3) return value.codes.join(", ");
    return `${value.codes.slice(0, 3).join(", ")} +${value.codes.length - 3} more`;
  };

  return (
    <div className="space-y-2">
      <Label>Select Options</Label>
      <Popover open={isOpen} onOpenChange={setIsOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={isOpen}
            className={cn(
              "w-full justify-between",
              value.codes.length === 0 && "text-muted-foreground"
            )}
          >
            <span className="truncate">{getDisplayText()}</span>
            <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-full p-0">
          <div className="p-2 space-y-2">
            {searchable && (
              <div className="relative">
                <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search options..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="pl-8"
                />
              </div>
            )}

            {showSelectAll && (
              <div className="flex gap-2 pb-2 border-b">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleSelectAll}
                  className="flex-1"
                >
                  Select All
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleSelectNone}
                  className="flex-1"
                >
                  Select None
                </Button>
              </div>
            )}

            <div className="max-h-[200px] overflow-auto space-y-1">
              {filteredOptions.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-2">
                  No options found
                </p>
              ) : (
                filteredOptions.map((option) => (
                  <div
                    key={option}
                    className="flex items-center space-x-2 p-2 hover:bg-accent rounded-sm cursor-pointer"
                    onClick={() => handleToggleOption(option)}
                  >
                    <Checkbox
                      checked={value.codes.includes(option)}
                      onCheckedChange={() => handleToggleOption(option)}
                      onClick={(e) => e.stopPropagation()}
                    />
                    <Label
                      htmlFor={option}
                      className="text-sm font-normal cursor-pointer flex-1"
                    >
                      {option}
                    </Label>
                  </div>
                ))
              )}
            </div>

            <div className="pt-2 border-t">
              <p className="text-xs text-muted-foreground">
                {value.codes.length} selected
              </p>
            </div>
          </div>
        </PopoverContent>
      </Popover>

      {error && (
        <p className="text-sm text-danger mt-1">{error}</p>
      )}
    </div>
  );
};
