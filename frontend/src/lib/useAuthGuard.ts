"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, getEnvironment } from "@/lib/api";

export function useAuthGuard() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [environment, setEnv] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    const cachedEnv = getEnvironment();
    api
      .me()
      .then((me) => {
        setEnv(me.environment);
        setEmail(me.email);
        setReady(true);
      })
      .catch(() => {
        router.replace("/command-center");
      });
    if (cachedEnv) setEnv(cachedEnv);
  }, [router]);

  return { ready, environment, email };
}
