import React, { useEffect, useState } from "react";
import Login from "./pages/login";
import ProfileSetup from "./pages/ProfileSetup";
import CareerDNALight from "./pages/CareerDNALight";
import { getCurrentUser, getProfile, logout } from "./api";

export default function App() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);
  const [profileReady, setProfileReady] = useState(null);
  const [editingProfile, setEditingProfile] = useState(false);

  async function checkUserProfile(currentUser) {
    const token = localStorage.getItem("careerdna_token");

    if (!token || !currentUser) {
      setProfileReady(null);
      return;
    }

    try {
      await getProfile();
      setProfileReady(true);
    } catch (error) {
      const message = error?.message || "";

      if (
        message.includes("No CareerDNA profile") ||
        message.includes("404")
      ) {
        setProfileReady(false);
      } else {
        console.error("Profile check failed:", error);
        setProfileReady(true);
      }
    }
  }

  useEffect(() => {
    const handleSessionExpired = () => {
      setUser(null);
      setProfileReady(null);
    };

    window.addEventListener("careerdna:logout", handleSessionExpired);

    async function checkSession() {
      const token = localStorage.getItem("careerdna_token");

      if (!token) {
        setUser(null);
        setProfileReady(null);
        setChecking(false);
        return;
      }

      try {
        const currentUser = await getCurrentUser();
        setUser(currentUser);
        await checkUserProfile(currentUser);
      } catch (error) {
        console.error("Session check failed:", error);

        localStorage.removeItem("careerdna_token");
        localStorage.removeItem("careerdna_user");
        setUser(null);
        setProfileReady(null);
      } finally {
        setChecking(false);
      }
    }

    checkSession();

    return () => {
      window.removeEventListener(
        "careerdna:logout",
        handleSessionExpired
      );
    };
  }, []);

  useEffect(() => {
    if (user) {
      setChecking(false);
      checkUserProfile(user);
    }
  }, [user]);

  async function handleSignOut() {
    await logout();
    setUser(null);
    setProfileReady(null);
    setEditingProfile(false);
  }

  function handleProfileComplete() {
    setEditingProfile(false);
    setProfileReady(true);
  }

  function handleEditProfile() {
    setEditingProfile(true);
  }

  function handleCancelEdit() {
    setEditingProfile(false);
  }

  async function handleBackToLogin() {
    await logout();
    setUser(null);
    setProfileReady(null);
  }

  if (checking) {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#F7F8FA",
          color: "#18263A",
          fontFamily:
            "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
        }}
      >
        <div
          style={{
            textAlign: "center",
            padding: "32px",
          }}
        >
          <div
            style={{
              width: "38px",
              height: "38px",
              border: "3px solid #E4E8EE",
              borderTopColor: "#3868A3",
              borderRadius: "50%",
              margin: "0 auto 16px",
              animation: "spin 0.8s linear infinite",
            }}
          />

          <div
            style={{
              fontSize: "16px",
              fontWeight: 600,
            }}
          >
            Loading CareerDNA...
          </div>

          <style>
            {`
              @keyframes spin {
                from {
                  transform: rotate(0deg);
                }
                to {
                  transform: rotate(360deg);
                }
              }
            `}
          </style>
        </div>
      </div>
    );
  }

  if (!user) {
    return <Login onLogin={setUser} />;
  }

  if (profileReady === false) {
    return (
      <ProfileSetup
        user={user}
        onComplete={handleProfileComplete}
        onBackToLogin={handleBackToLogin}
      />
    );
  }

  if (editingProfile) {
    return (
      <ProfileSetup
        user={user}
        mode="edit"
        onComplete={handleProfileComplete}
        onCancel={handleCancelEdit}
        onBackToLogin={handleBackToLogin}
      />
    );
  }

  return (
    <CareerDNALight
      user={user}
      onSignOut={handleSignOut}
      onEditProfile={handleEditProfile}
    />
  );
}