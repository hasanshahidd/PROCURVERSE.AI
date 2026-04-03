import { useState, useEffect, useRef } from "react";
import { Mic, MicOff, Volume2, VolumeX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface VoiceInputProps {
  onTranscript: (text: string) => void;
  language: string;
  voiceOutputEnabled: boolean;
  onVoiceOutputToggle: (enabled: boolean) => void;
  labelClassName?: string;
  activeIconClassName?: string;
  inactiveIconClassName?: string;
}

const languageMap: Record<string, string> = {
  en: "en-US",
  ar: "ar-SA",
};

export function VoiceInput({
  onTranscript,
  language,
  voiceOutputEnabled,
  onVoiceOutputToggle,
  labelClassName,
  activeIconClassName,
  inactiveIconClassName,
}: VoiceInputProps) {
  const [isListening, setIsListening] = useState(false);
  const [isSupported, setIsSupported] = useState(true);
  const recognitionRef = useRef<any>(null);

  useEffect(() => {
    const SpeechRecognition =
      (window as any).SpeechRecognition ||
      (window as any).webkitSpeechRecognition;

    if (!SpeechRecognition) {
      setIsSupported(false);
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = languageMap[language] || "en-US";

    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript;
      onTranscript(transcript);
      setIsListening(false);
    };

    recognition.onerror = () => {
      setIsListening(false);
    };

    recognition.onend = () => {
      setIsListening(false);
    };

    recognitionRef.current = recognition;

    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.abort();
      }
    };
  }, [language, onTranscript]);

  const toggleListening = () => {
    if (!recognitionRef.current) return;

    if (isListening) {
      recognitionRef.current.abort();
      setIsListening(false);
    } else {
      recognitionRef.current.lang = languageMap[language] || "en-US";
      recognitionRef.current.start();
      setIsListening(true);
    }
  };

  return (
    <div className="flex items-center gap-4">
      <div className="flex items-center gap-2">
        <Switch
          id="voice-output"
          checked={voiceOutputEnabled}
          onCheckedChange={onVoiceOutputToggle}
          data-testid="switch-voice-output"
        />
        <Label
          htmlFor="voice-output"
          className={cn("flex items-center gap-1.5 text-sm cursor-pointer", labelClassName)}
        >
          {voiceOutputEnabled ? (
            <Volume2 className={cn("h-4 w-4", activeIconClassName)} />
          ) : (
            <VolumeX className={cn("h-4 w-4", inactiveIconClassName)} />
          )}
          <span className="hidden sm:inline">Voice</span>
        </Label>
      </div>
      {isSupported ? (
        <Button
          size="icon"
          variant={isListening ? "default" : "outline"}
          onClick={toggleListening}
          data-testid="button-voice-input"
          aria-label={isListening ? "Stop listening" : "Start voice input"}
          className={isListening ? "animate-pulse" : ""}
        >
          {isListening ? (
            <Mic className="h-5 w-5" />
          ) : (
            <MicOff className="h-5 w-5" />
          )}
        </Button>
      ) : (
        <Badge variant="secondary" className="text-xs" data-testid="badge-voice-unsupported">
          Voice N/A
        </Badge>
      )}
    </div>
  );
}

export function speakText(text: string, language: string) {
  if (!("speechSynthesis" in window)) return;
  
  window.speechSynthesis.cancel();
  
  // Strip markdown formatting for better speech output
  let cleanText = text
    .replace(/#{1,6}\s/g, '') // Remove headings
    .replace(/\*\*([^*]+)\*\*/g, '$1') // Remove bold
    .replace(/\*([^*]+)\*/g, '$1') // Remove italic
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1') // Remove links, keep text
    .replace(/`([^`]+)`/g, '$1') // Remove code blocks
    .replace(/\|/g, ' ') // Remove table pipes
    .replace(/---+/g, '') // Remove horizontal rules
    .replace(/^\s*[-*+]\s+/gm, '') // Remove list markers
    .replace(/^\s*\d+\.\s+/gm, '') // Remove numbered list markers
    .replace(/\n\n+/g, '. ') // Double newlines become periods
    .replace(/\n/g, ' ') // Single newlines become spaces
    .trim();
  
  // Limit length for speech (first 500 chars)
  if (cleanText.length > 500) {
    cleanText = cleanText.substring(0, 500) + "... response truncated for voice output.";
  }
  
  const utterance = new SpeechSynthesisUtterance(cleanText);
  utterance.lang = languageMap[language] || "en-US";
  utterance.rate = 0.85; // Slightly slower for better clarity
  utterance.pitch = 1;
  utterance.volume = 1;
  
  // Wait for voices to load
  const speakWithVoice = () => {
    const voices = window.speechSynthesis.getVoices();
    const targetLang = languageMap[language] || "en-US";
    
    // Find appropriate voice for the language
    let selectedVoice = voices.find(voice => 
      voice.lang.startsWith(targetLang.split('-')[0])
    );
    
    // For Arabic, prefer specific Arabic voices
    if (language === 'ar') {
      const arabicVoice = voices.find(voice => 
        voice.lang.includes('ar') || voice.name.includes('Arabic')
      );
      if (arabicVoice) selectedVoice = arabicVoice;
    }
    
    if (selectedVoice) {
      utterance.voice = selectedVoice;
    }
    
    window.speechSynthesis.cancel(); // Cancel any ongoing speech
    window.speechSynthesis.speak(utterance);
  };
  
  // Voices might not be loaded immediately
  if (window.speechSynthesis.getVoices().length > 0) {
    speakWithVoice();
  } else {
    window.speechSynthesis.addEventListener('voiceschanged', speakWithVoice, { once: true });
  }
}
