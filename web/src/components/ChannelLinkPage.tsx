import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Link2, Loader2 } from "@/lib/lucide";
import { toast } from 'sonner';
import Navigation from './Navigation';
import { useAuth } from '@/contexts/auth-core';
import { completeChannelLink, getChannelLinkStatus } from '@/utils/api';
import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';

/**
 * Public channel-account linking page.
 */
function ChannelLinkPage() {
  const { token = '' } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const { user, login } = useAuth();
  const [status, setStatus] = useState<Awaited<ReturnType<typeof getChannelLinkStatus>> | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    const loadStatus = async () => {
      setIsLoading(true);
      try {
        const nextStatus = await getChannelLinkStatus(token);
        setStatus(nextStatus);
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : 'Failed to load channel link');
      } finally {
        setIsLoading(false);
      }
    };
    void loadStatus();
  }, [token]);

  const handleLogin = async () => {
    setIsSubmitting(true);
    setErrorMessage('');
    try {
      await login(username, password);
      toast.success('Signed in successfully');
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Login failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleComplete = async () => {
    setIsSubmitting(true);
    try {
      await completeChannelLink(token);
      toast.success('Channel account linked');
      if (status) {
        navigate(`/agent/${status.agent_id}`, { replace: true });
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to complete linking');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Navigation />
      <div className="mx-auto flex min-h-[calc(100vh-48px)] max-w-2xl items-center justify-center px-4 py-8">
        <div className="w-full rounded-2xl border border-border bg-card p-6 shadow-sm">
          <div className="mb-6 text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
              <Link2 className="h-7 w-7" />
            </div>
            <h1 className="text-2xl font-semibold">Link Channel Account</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Bind this external channel identity to your Pivot workspace before chatting with the agent.
            </p>
          </div>

          {isLoading ? (
            <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading channel link…
            </div>
          ) : status ? (
            <div className="space-y-6">
              <div className="rounded-xl border border-border px-4 py-3">
                <div className="text-sm font-medium text-foreground">{status.provider_name}</div>
                <div className="mt-1 text-sm text-muted-foreground">
                  Binding: {status.binding_name}
                </div>
                <div className="mt-1 text-sm text-muted-foreground">
                  External user: {status.external_user_id}
                </div>
                <div className="mt-1 text-sm text-muted-foreground">
                  Status: {status.status}
                </div>
              </div>

              {!user ? (
                <div className="space-y-4">
                  <Field data-invalid={!!errorMessage}>
                    <FieldLabel htmlFor="channel-link-username">Username</FieldLabel>
                    <Input
                      id="channel-link-username"
                      value={username}
                      onChange={(event) => setUsername(event.target.value)}
                      autoComplete="username"
                    />
                  </Field>
                  <Field data-invalid={!!errorMessage}>
                    <FieldLabel htmlFor="channel-link-password">Password</FieldLabel>
                    <Input
                      id="channel-link-password"
                      type="password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      autoComplete="current-password"
                    />
                    {errorMessage && <FieldError>{errorMessage}</FieldError>}
                  </Field>
                  <Button className="w-full" onClick={() => void handleLogin()} disabled={isSubmitting}>
                    {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                    Sign in to continue
                  </Button>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="rounded-xl border border-border px-4 py-3 text-sm text-muted-foreground">
                    Signed in as <span className="font-medium text-foreground">{user.username}</span>.
                  </div>
                  {errorMessage && (
                    <div className="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                      {errorMessage}
                    </div>
                  )}
                  <Button className="w-full" onClick={() => void handleComplete()} disabled={isSubmitting || status.status !== 'pending'}>
                    {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                    {status.status === 'pending' ? 'Complete Linking' : 'Link Unavailable'}
                  </Button>
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              {errorMessage || 'Channel link not found'}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default ChannelLinkPage;
