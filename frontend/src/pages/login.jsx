import React, {
  useState,
} from "react";

import {
  login,
  register,
} from "../api";


const C = {

  page: "#F7F8FA",

  white: "#FFFFFF",

  border: "#E4E8EE",

  text: "#18263A",

  text2: "#44536A",

  muted: "#7A8798",

  blue: "#3868A3",

  blueDark: "#284D7A",

  blueSoft: "#EEF3F9",

  red: "#C56B6B",

};


const labelStyle = {

  display: "block",

  color: C.muted,

  fontSize: 9,

  fontWeight: 700,

  letterSpacing: "0.8px",

  marginBottom: 7,

};


const inputStyle = {

  width: "100%",

  boxSizing: "border-box",

  border: `1px solid ${C.border}`,

  borderRadius: 7,

  padding: "12px",

  fontSize: 12,

  color: C.text,

  outline: "none",

  background: C.white,

};


export default function Login({
  onLogin,
}) {

  const [
    mode,
    setMode,
  ] = useState("login");


  const [
    name,
    setName,
  ] = useState("");


  const [
    email,
    setEmail,
  ] = useState("");


  const [
    password,
    setPassword,
  ] = useState("");


  const [
    loading,
    setLoading,
  ] = useState(false);


  const [
    error,
    setError,
  ] = useState("");


  async function handleSubmit(
    event
  ) {

    event.preventDefault();

    setError("");

    setLoading(true);


    try {

      let result;


      if (mode === "login") {

        result = await login(
          email,
          password
        );

      } else {

        result = await register(
          name,
          email,
          password
        );
      }


      localStorage.setItem(
        "careerdna_token",
        result.access_token
      );


      localStorage.setItem(
        "careerdna_user",
        JSON.stringify(
          result.user
        )
      );


      onLogin(
        result.user
      );


    } catch (error) {

      console.error(error);

      setError(
        error.message ||
        "Something went wrong."
      );

    } finally {

      setLoading(false);
    }
  }


  function switchMode() {

    setMode(
      current =>
        current === "login"
          ? "register"
          : "login"
    );

    setError("");
  }


  return (

    <div
      style={{
        minHeight: "100vh",
        background: C.page,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
        fontFamily:
          "Inter, Arial, sans-serif",
      }}
    >

      <div
        style={{
          width: "100%",
          maxWidth: 420,
          background: C.white,
          border:
            `1px solid ${C.border}`,
          borderRadius: 12,
          padding: 34,
          boxShadow:
            "0 8px 30px rgba(31,50,75,.07)",
        }}
      >

        <div
          style={{
            fontFamily:
              "'Space Grotesk', Inter, sans-serif",
            fontSize: 25,
            fontWeight: 700,
            color: C.blueDark,
          }}
        >
          CareerDNA
        </div>


        <div
          style={{
            marginTop: 6,
            color: C.muted,
            fontSize: 12,
          }}
        >
          Evidence-based career intelligence
        </div>


        <div
          style={{
            height: 1,
            background: C.border,
            margin: "25px 0",
          }}
        />


        <h1
          style={{
            margin: 0,
            color: C.text,
            fontSize: 24,
          }}
        >
          {mode === "login"
            ? "Welcome back"
            : "Create your account"}
        </h1>


        <p
          style={{
            color: C.muted,
            fontSize: 12,
            marginTop: 7,
            marginBottom: 24,
          }}
        >
          {mode === "login"
            ? "Sign in to access your CareerDNA profile."
            : "Create an account to build your CareerDNA profile."}
        </p>


        <form
          onSubmit={
            handleSubmit
          }
        >

          {mode === "register" && (

            <div
              style={{
                marginBottom: 16,
              }}
            >

              <label
                style={labelStyle}
              >
                FULL NAME
              </label>


              <input
                value={name}
                onChange={
                  event =>
                    setName(
                      event.target.value
                    )
                }
                placeholder="Your name"
                required
                style={inputStyle}
              />

            </div>

          )}


          <div
            style={{
              marginBottom: 16,
            }}
          >

            <label
              style={labelStyle}
            >
              EMAIL
            </label>


            <input
              type="email"
              value={email}
              onChange={
                event =>
                  setEmail(
                    event.target.value
                  )
              }
              placeholder="you@example.com"
              required
              style={inputStyle}
            />

          </div>


          <div
            style={{
              marginBottom: 16,
            }}
          >

            <label
              style={labelStyle}
            >
              PASSWORD
            </label>


            <input
              type="password"
              value={password}
              onChange={
                event =>
                  setPassword(
                    event.target.value
                  )
              }
              placeholder="Enter your password"
              required
              minLength={6}
              style={inputStyle}
            />

          </div>


          {error && (

            <div
              style={{
                background: "#FFF4F4",
                border:
                  "1px solid #F0D5D5",
                color: C.red,
                borderRadius: 7,
                padding:
                  "10px 12px",
                fontSize: 11,
                marginBottom: 16,
              }}
            >
              {error}
            </div>

          )}


          <button
            type="submit"
            disabled={loading}
            style={{
              width: "100%",
              border: 0,
              background: C.blueDark,
              color: "#FFFFFF",
              padding:
                "12px 16px",
              borderRadius: 7,
              fontSize: 13,
              fontWeight: 700,
              cursor:
                loading
                  ? "default"
                  : "pointer",
              opacity:
                loading
                  ? 0.7
                  : 1,
            }}
          >

            {loading
              ? "Please wait..."
              : mode === "login"
              ? "Sign in"
              : "Create account"}

          </button>

        </form>


        <div
          style={{
            textAlign: "center",
            marginTop: 22,
            color: C.muted,
            fontSize: 11,
          }}
        >

          {mode === "login"
            ? "Don't have an account?"
            : "Already have an account?"}


          <button
            type="button"
            onClick={switchMode}
            style={{
              border: 0,
              background:
                "transparent",
              color: C.blueDark,
              fontWeight: 700,
              marginLeft: 5,
              cursor: "pointer",
              fontSize: 11,
            }}
          >

            {mode === "login"
              ? "Create one"
              : "Sign in"}

          </button>

        </div>

      </div>

    </div>

  );
}