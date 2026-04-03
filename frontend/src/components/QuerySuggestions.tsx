import { useEffect, useState } from "react";
import { Lightbulb, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { apiRequest } from "@/lib/queryClient";

interface QuerySuggestion {
  id: string;
  text: string;
  category: string;
}

interface QuerySuggestionsProps {
  input: string;
  language: string;
  conversationContext: string[];
  onSelect: (suggestion: string) => void;
  selectedIndex: number;
  onIndexChange: (index: number) => void;
}

const QuerySuggestions = ({
  input,
  language,
  conversationContext,
  onSelect,
  selectedIndex,
  onIndexChange,
}: QuerySuggestionsProps) => {
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  // Fetch suggestions from backend with debouncing
  useEffect(() => {
    // Only fetch if input is at least 3 characters
    if (!input || input.trim().length < 3) {
      setSuggestions([]);
      return;
    }

    setIsLoading(true);
    
    // Debounce: wait 300ms after user stops typing
    const timer = setTimeout(async () => {
      try {
        const res = await apiRequest("POST", "/api/suggestions", {
          partial_input: input,
          language: language,
          conversation_context: conversationContext,
        });

        const response = await res.json();
        setSuggestions(response.suggestions || []);
      } catch (error) {
        console.error("Failed to fetch suggestions:", error);
        setSuggestions([]);
      } finally {
        setIsLoading(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [input, language, conversationContext]);

  // Reset selected index when suggestions change
  useEffect(() => {
    if (suggestions.length > 0) {
      onIndexChange(0);
    } else {
      onIndexChange(-1);
    }
  }, [suggestions, onIndexChange]);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground p-2">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span>Generating suggestions...</span>
      </div>
    );
  }

  if (suggestions.length === 0) {
    return null;
  }

  return (
    <div className="mb-3 space-y-2">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Lightbulb className="w-4 h-4" />
        <span>{language === "ar" ? "اقتراحات ذكية" : "Smart Suggestions"}</span>
      </div>
      
      <div className="flex flex-wrap gap-2">
        {suggestions.map((suggestion, index) => (
          <button
            key={index}
            onClick={() => onSelect(suggestion)}
            className={cn(
              "px-3 py-2 text-sm rounded-lg border transition-all",
              "hover:border-primary hover:bg-primary/5",
              "focus:outline-none focus:ring-2 focus:ring-primary/50",
              selectedIndex === index 
                ? "border-primary bg-primary/10 font-medium" 
                : "border-border bg-background"
            )}
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
};

export default QuerySuggestions;

