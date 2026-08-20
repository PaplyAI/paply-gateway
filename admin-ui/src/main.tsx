import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '@/api/client';
import { AppContainer } from '@/components/app';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Toaster } from '@/components/ui/sonner';
import { ThemeProvider } from '@/provider/theme';
import './globals.css';

createRoot(document.getElementById('root')!).render(
  <ThemeProvider>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <AppContainer />
        <Toaster
          position="top-left"
          toastOptions={{
            classNames: {
              success: '[&_[data-icon]]:text-primary',
              error: '[&_[data-icon]]:text-destructive',
              warning: '[&_[data-icon]]:text-destructive/70',
            },
          }}
        />
      </TooltipProvider>
    </QueryClientProvider>
  </ThemeProvider>,
);
