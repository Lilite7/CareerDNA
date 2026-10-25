import React, { useEffect, useMemo, useState } from "react";

import {
  getProfile,
  getSkills,
  getSalary,
  getCareerGap,
  getJobMatch,
  getCareerHistory,
  runWhatIf,
} from "../api";

import AIAssistant from "./AIAssistant";

import {
  ResponsiveContainer,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  LineChart,
  Line,
  Cell,
} from "recharts";

/* =========================================================
   CareerDNA — Light UI
   ========================================================= */

const C = {
  page: "#F7F8FA",
  white: "#FFFFFF",
  border: "#E4E8EE",
  soft: "#EEF1F5",
  text: "#18263A",
  text2: "#44536A",
  muted: "#7A8798",
  blue: "#3868A3",
  blueDark: "#284D7A",
  blueSoft: "#EEF3F9",
  amber: "#C79336",
  red: "#C56B6B",
  green: "#4B8C78",
  track: "#E9EDF2",
};

/* =========================================================
   STATIC FALLBACK DATA
   ========================================================= */

const defaultSkills = [];
const defaultRadarData = [];
const defaultHistory = [];

const simulationOptions = [
  {
    id: "aws",
    label: "AWS Cloud Practitioner certification",
    impact: 0.8,
  },
  {
    id: "ml",
    label: "One more high-impact ML project",
    impact: 0.7,
  },
  {
    id: "internship",
    label: "Another 6-month internship",
    impact: 1.9,
  },
  {
    id: "docker",
    label: "Docker + containerized deployment",
    impact: 0.5,
  },
];

const NAV = [
  "Overview",
  "Skills",
  "Salary Forecast",
  "Career Simulator",
  "Career Gap",
  "Time Machine",
  "AI Assistant",
];

/* =========================================================
   BASIC COMPONENTS
   ========================================================= */

function Card({ children, style = {} }) {
  return (
    <section
      style={{
        background: C.white,
        border: `1px solid ${C.border}`,
        borderRadius: 9,
        boxShadow: "0 1px 2px rgba(20,35,55,.025)",
        ...style,
      }}
    >
      {children}
    </section>
  );
}

function EmptyState({ text }) {
  return (
    <div style={{ padding: "28px 12px", color: C.muted, fontSize: 12, lineHeight: 1.6, textAlign: "center" }}>
      {text}
    </div>
  );
}

function SectionTitle({ title, subtitle, right }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        gap: 16,
        marginBottom: 20,
      }}
    >
      <div>
        <h2
          style={{
            margin: 0,
            color: C.text,
            fontFamily: "'Space Grotesk', Inter, sans-serif",
            fontSize: 16,
            fontWeight: 700,
          }}
        >
          {title}
        </h2>

        {subtitle && (
          <div
            style={{
              marginTop: 5,
              color: C.muted,
              fontSize: 12,
            }}
          >
            {subtitle}
          </div>
        )}
      </div>

      {right}
    </div>
  );
}

function Badge({ text, tone = "gray" }) {
  const styles = {
    green: ["#EDF7F3", C.green],
    amber: ["#FBF5E9", "#9A6E22"],
    red: ["#FBEEEE", C.red],
    gray: ["#F1F3F6", C.muted],
  };

  const [background, color] = styles[tone] || styles.gray;

  return (
    <span
      style={{
        display: "inline-flex",
        padding: "3px 7px",
        borderRadius: 4,
        background,
        color,
        fontSize: 8.5,
        fontWeight: 700,
        whiteSpace: "nowrap",
      }}
    >
      {text}
    </span>
  );
}

function StatCard({
  label,
  value,
  sub,
  valueColor = C.text,
}) {
  return (
    <Card
      style={{
        minHeight: 76,
        padding: "15px 17px",
      }}
    >
      <div
        style={{
          color: C.muted,
          textTransform: "uppercase",
          letterSpacing: ".75px",
          fontSize: 9,
          fontWeight: 700,
          marginBottom: 7,
        }}
      >
        {label}
      </div>

      <div
        style={{
          color: valueColor,
          fontFamily: "'Space Grotesk', Inter, sans-serif",
          fontWeight: 700,
          fontSize: 18,
        }}
      >
        {value}
      </div>

      {sub && (
        <div
          style={{
            color: C.muted,
            fontSize: 10,
            marginTop: 5,
          }}
        >
          {sub}
        </div>
      )}
    </Card>
  );
}

function SkillBar({ skill, compact = false }) {
  return (
    <div style={{ marginBottom: compact ? 12 : 15 }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: compact
            ? "110px 1fr 28px"
            : "145px 1fr 28px",
          gap: 14,
          alignItems: "center",
        }}
      >
        <div
          style={{
            color: C.text,
            fontWeight: 600,
            fontSize: 12,
          }}
        >
          {skill.name}
        </div>

        <div
          style={{
            height: 7,
            background: C.track,
            borderRadius: 99,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: `${skill.score}%`,
              height: "100%",
              background: skill.color || C.blue,
              borderRadius: 99,
            }}
          />
        </div>

        <div
          style={{
            textAlign: "right",
            color: C.text,
            fontSize: 11,
            fontWeight: 700,
          }}
        >
          {skill.score}
        </div>
      </div>

      {skill.evidence && (
        <div
          style={{
            marginLeft: compact ? 124 : 159,
            marginTop: 4,
            color: C.muted,
            fontSize: 9.5,
          }}
        >
          {skill.evidence}
        </div>
      )}
    </div>
  );
}

/* =========================================================
   RADAR
   ========================================================= */

function ProfileRadar({ data = defaultRadarData }) {
  if (!data.length) {
    return <EmptyState text="Add profile evidence to see your CareerDNA composition." />;
  }

  return (
    <div
      style={{
        width: "100%",
        height: 235,
      }}
    >
      <ResponsiveContainer>
        <RadarChart
          data={data}
          cx="50%"
          cy="50%"
          outerRadius="65%"
        >
          <PolarGrid stroke="#DDE3EA" />

          <PolarAngleAxis
            dataKey="subject"
            tick={{
              fill: C.muted,
              fontSize: 9,
            }}
          />

          <PolarRadiusAxis
            angle={90}
            domain={[0, 100]}
            tick={false}
            axisLine={false}
          />

          <Radar
            dataKey="value"
            stroke={C.blue}
            fill="#AFC3DC"
            fillOpacity={0.34}
            strokeWidth={2}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* =========================================================
   HELIX
   ========================================================= */

function Helix() {
  const xs = [90, 170, 250, 330, 410, 490, 570, 650, 730];

  return (
    <div
      style={{
        border: `1px solid ${C.soft}`,
        borderRadius: 8,
        background: "#FCFDFE",
        padding: "14px 18px 10px",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: 8,
          marginBottom: 5,
        }}
      >
        <b style={{ color: C.blue, fontSize: 10 }}>
          EDUCATION
        </b>

        <b style={{ color: C.green, fontSize: 10 }}>
          EXPERIENCE
        </b>

        <b style={{ color: C.amber, fontSize: 10 }}>
          MARKET
        </b>
      </div>

      <svg
        viewBox="0 0 800 170"
        width="100%"
        height="150"
      >
        <path
          d="M50 35 C160 115,250 115,360 35 S560 -45,750 35"
          fill="none"
          stroke={C.blue}
          strokeWidth="4"
          strokeLinecap="round"
        />

        <path
          d="M50 135 C160 55,250 55,360 135 S560 215,750 135"
          fill="none"
          stroke={C.amber}
          strokeWidth="4"
          strokeLinecap="round"
        />

        {xs.map((x, i) => {
          const y1 = 45 + Math.sin(i * 0.7) * 22;
          const y2 = 125 - Math.sin(i * 0.7) * 22;

          return (
            <line
              key={x}
              x1={x}
              y1={y1}
              x2={x}
              y2={y2}
              stroke="#C7D1DE"
              strokeWidth="2"
            />
          );
        })}

        <circle
          cx="170"
          cy="95"
          r="5"
          fill={C.blue}
        />

        <circle
          cx="410"
          cy="95"
          r="5"
          fill={C.amber}
        />

        <circle
          cx="650"
          cy="95"
          r="5"
          fill={C.green}
        />

        <text
          x="170"
          y="158"
          textAnchor="middle"
          fill={C.muted}
          fontSize="11"
        >
          Skills
        </text>

        <text
          x="410"
          y="158"
          textAnchor="middle"
          fill={C.muted}
          fontSize="11"
        >
          Projects
        </text>

        <text
          x="650"
          y="158"
          textAnchor="middle"
          fill={C.muted}
          fontSize="11"
        >
          Outcomes
        </text>
      </svg>
    </div>
  );
}

/* =========================================================
   HEADER
   ========================================================= */

function Header({ user, onSignOut, onEditProfile }) {
  const initials =
    user?.name
      ?.split(" ")
      .map((x) => x[0])
      .join("")
      .slice(0, 2)
      .toUpperCase() || "CD";

  return (
    <div
      style={{
        height: 67,
        borderBottom: `1px solid ${C.border}`,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}
    >
      <div
        style={{
          color: "#8A95A5",
          fontSize: 10,
        }}
      >
        CareerDNA / Career profile
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <div
          style={{
            width: 34,
            height: 34,
            borderRadius: "50%",
            background: C.blueDark,
            color: C.white,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 11,
            fontWeight: 700,
          }}
        >
          {initials}
        </div>

        <div>
          <div
            style={{
              color: C.text,
              fontSize: 11,
              fontWeight: 700,
            }}
          >
            {user?.name || "CareerDNA User"}
          </div>

          <div
            style={{
              color: C.muted,
              fontSize: 9,
              marginTop: 2,
            }}
          >
            {user?.email || "Personal CareerDNA workspace"}
          </div>
        </div>

        {onEditProfile && (
          <button
            onClick={onEditProfile}
            style={{
              marginLeft: 12,
              border: "1px solid #DCE2E9",
              background: C.white,
              color: C.text2,
              borderRadius: 6,
              padding: "7px 11px",
              fontSize: 10,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Update Profile
          </button>
        )}

        {onSignOut && (
          <button
            onClick={onSignOut}
            style={{
              marginLeft: 12,
              border: "1px solid #DCE2E9",
              background: C.white,
              color: C.text2,
              borderRadius: 6,
              padding: "7px 11px",
              fontSize: 10,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Sign out
          </button>
        )}
      </div>
    </div>
  );
}

/* =========================================================
   MINI FACT
   ========================================================= */

function MiniFact({ label, value }) {
  return (
    <div
      style={{
        paddingRight: 12,
        borderRight: `1px solid ${C.soft}`,
      }}
    >
      <div
        style={{
          color: C.muted,
          fontSize: 8,
          fontWeight: 700,
          letterSpacing: ".7px",
          marginBottom: 5,
        }}
      >
        {label}
      </div>

      <div
        style={{
          color: C.text2,
          fontSize: 10,
          fontWeight: 700,
        }}
      >
        {value}
      </div>
    </div>
  );
}

/* =========================================================
   PROJECTS
   ========================================================= */

function Projects({ profileProjects = [], compact = false }) {
  const projectRows = profileProjects.map((project) => ({
    name: project.title || "Untitled project",
    stack: Array.isArray(project.skills) ? project.skills.join(" · ") : project.skills || "Profile project",
    impact: project.impact || "Unrated",
    type: project.solo ? "Independent" : "Collaborative",
  }));
  const rows = compact ? projectRows.slice(0, 3) : projectRows;

  return (
    <div style={{ overflowX: "auto" }}>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          minWidth: 500,
        }}
      >
        <thead>
          <tr>
            {["PROJECT", "IMPACT", "TYPE"].map((h) => (
              <th
                key={h}
                style={{
                  textAlign: "left",
                  padding: "0 0 9px",
                  color: C.muted,
                  fontSize: 8,
                  letterSpacing: ".7px",
                }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>

        <tbody>
          {rows.map((p) => (
            <tr key={p.name}>
              <td
                style={{
                  padding: "10px 8px 10px 0",
                  borderTop: `1px solid ${C.soft}`,
                }}
              >
                <div
                  style={{
                    color: C.text,
                    fontSize: 11,
                    fontWeight: 700,
                  }}
                >
                  {p.name}
                </div>

                <div
                  style={{
                    color: C.muted,
                    fontSize: 9,
                    marginTop: 3,
                  }}
                >
                  {p.stack}
                </div>
              </td>

              <td
                style={{
                  borderTop: `1px solid ${C.soft}`,
                }}
              >
                <Badge
                  text={p.impact}
                  tone={
                    p.impact === "High"
                      ? "green"
                      : "amber"
                  }
                />
              </td>

              <td
                style={{
                  borderTop: `1px solid ${C.soft}`,
                }}
              >
                <Badge text={p.type} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* =========================================================
   OVERVIEW
   ========================================================= */

function Overview({ profile, skillsData, salaryData }) {
  const displaySkills =
    Array.isArray(skillsData) && skillsData.length
      ? skillsData
      : defaultSkills;
  const candidate = profile?.candidate || {};
  const education = profile?.education || [];
  const experience = profile?.experience || [];
  const profileProjects = profile?.projects || [];
  const certifications = profile?.certifications || [];
  const topSkill = displaySkills[0];
  const salary = Number(salaryData?.predicted_salary_lpa ?? salaryData?.predicted_salary ?? 0);
  const profileStrength = Math.min(100, Math.round(
    ((education.length > 0) + (experience.length > 0) + (displaySkills.length > 0) + (profileProjects.length > 0) + (certifications.length > 0)) * 20
  ));
  const radarData = [
    { subject: "Education", value: education.length ? 100 : 0 },
    { subject: "Skills", value: Math.min(100, displaySkills.length * 20) },
    { subject: "Projects", value: Math.min(100, profileProjects.length * 25) },
    { subject: "Experience", value: Math.min(100, experience.length * 25) },
    { subject: "Certifications", value: Math.min(100, certifications.length * 25) },
  ];

  return (
    <>
      <div
        className="grid4"
        style={{
          display: "grid",
          gridTemplateColumns:
            "repeat(4, minmax(0, 1fr))",
          gap: 9,
          marginBottom: 11,
        }}
      >
        <StatCard
          label="Profile strength"
          value={`${profileStrength} / 100`}
          sub="Based on saved profile evidence"
        />

        <StatCard
          label="Estimated salary"
          value={salary ? `₹${salary.toFixed(1)}L` : "Not available"}
          sub={salaryData?.source === "database" ? "Saved model prediction" : "Complete more evidence for an estimate"}
          valueColor={C.amber}
        />

        <StatCard
          label="Top skill"
          value={topSkill ? `${topSkill.name || topSkill.skill_name} · ${Number(topSkill.score ?? topSkill.evidence_score ?? 0)}` : "No skills yet"}
          sub="Evidence-weighted score"
          valueColor={C.green}
        />

        <StatCard
          label="Projects"
          value={String(profileProjects.length)}
          sub="Saved projects"
        />
      </div>

      <div
        className="grid2"
        style={{
          display: "grid",
          gridTemplateColumns: "1.04fr .96fr",
          gap: 11,
          marginBottom: 11,
        }}
      >
        <Card style={{ padding: 17 }}>
          <SectionTitle
            title="Profile"
            subtitle="Current academic and professional snapshot"
          />

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              paddingBottom: 16,
              borderBottom: `1px solid ${C.soft}`,
            }}
          >
            <div
              style={{
                width: 42,
                height: 42,
                borderRadius: 6,
                background: C.blueSoft,
                color: C.blueDark,
                display: "grid",
                placeItems: "center",
                fontWeight: 700,
              }}
            >
              NK
            </div>

            <div>
              <b
                style={{
                  color: C.text,
                  fontSize: 13,
                }}
              >
                {candidate.name || "Your profile"}
              </b>

              <div
                style={{
                  color: C.muted,
                  fontSize: 10,
                  marginTop: 3,
                }}
              >
                {profile?.profile_snapshot?.headline || "Add a professional headline"}
              </div>

              <div
                style={{
                  color: C.muted,
                  fontSize: 10,
                  marginTop: 2,
                }}
              >
                {candidate.location || "Add your location"}
              </div>
            </div>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns:
                "repeat(3, 1fr)",
              marginTop: 15,
            }}
          >
            <MiniFact
              label="EDUCATION"
              value={education[0]?.cgpa ? `CGPA ${education[0].cgpa}` : "Not added"}
            />

            <MiniFact
              label="EXPERIENCE"
              value={experience.length ? `${experience.length} role${experience.length === 1 ? "" : "s"}` : "Not added"}
            />

            <MiniFact
              label="EVIDENCE"
              value={`${displaySkills.length} tracked skills`}
            />
          </div>
        </Card>

        <Card style={{ padding: 17 }}>
          <SectionTitle
            title="Profile composition"
            subtitle="Relative strength across the main evidence categories"
          />

          <ProfileRadar data={radarData} />
        </Card>
      </div>

      <div
        className="grid2"
        style={{
          display: "grid",
          gridTemplateColumns: "1.04fr .96fr",
          gap: 11,
        }}
      >
        <Card style={{ padding: 17 }}>
          <SectionTitle
            title="Skill evidence"
            subtitle="Evidence-weighted strength rather than self-reported ratings"
          />

          {displaySkills
            .slice(0, 4)
            .map((skill, index) => (
              <SkillBar
                key={
                  skill.name ||
                  skill.skill ||
                  index
                }
                skill={{
                  name:
                    skill.name ||
                    skill.skill ||
                    "Skill",
                  score:
                    Number(
                      skill.score ??
                        skill.value ??
                        0
                    ),
                  evidence:
                    skill.evidence || "",
                  color:
                    skill.color || C.blue,
                }}
                compact
              />
            ))}
        </Card>

        <Card style={{ padding: 17 }}>
          <SectionTitle
            title="Recent projects"
            subtitle="Projects contributing evidence to the profile"
          />

          {profileProjects.length ? <Projects profileProjects={profileProjects} compact /> : <EmptyState text="Add a project to see your evidence trail here." />}
        </Card>
      </div>
    </>
  );
}

/* =========================================================
   SKILLS
   ========================================================= */

function SkillsPage({ skillsData }) {
  const displaySkills =
    Array.isArray(skillsData) && skillsData.length
      ? skillsData.map((skill) => ({
          name:
            skill.name ||
            skill.skill ||
            "Skill",
          score: Number(
            skill.score ??
              skill.value ??
              0
          ),
          evidence:
            skill.evidence || "",
          color:
            skill.color || C.blue,
        }))
      : defaultSkills;

  const data = displaySkills.map((skill) => ({
    name: skill.name,
    score: skill.score,
    fill: skill.color,
  }));

  if (!displaySkills.length) {
    return <Card style={{ padding: 20 }}><SectionTitle title="Skill strength" subtitle="Evidence-weighted scores from your saved profile" /><EmptyState text="Add skills during onboarding to unlock your personalized strength map." /></Card>;
  }

  return (
    <Card style={{ padding: 20 }}>
      <SectionTitle
        title="Skill strength"
        subtitle="Evidence-weighted scores from the current profile"
      />

      {displaySkills.map((skill) => (
        <SkillBar
          key={skill.name}
          skill={skill}
        />
      ))}

      <div
        style={{
          height: 290,
          borderTop: `1px solid ${C.soft}`,
          paddingTop: 14,
          marginTop: 4,
        }}
      >
        <ResponsiveContainer>
          <BarChart
            data={data}
            layout="vertical"
            margin={{
              top: 3,
              right: 24,
              left: 0,
              bottom: 8,
            }}
          >
            <CartesianGrid
              stroke="#E5E9EE"
              horizontal={false}
            />

            <XAxis
              type="number"
              domain={[0, 100]}
              tick={{
                fill: C.muted,
                fontSize: 10,
              }}
              axisLine={{
                stroke: "#C8D0DA",
              }}
            />

            <YAxis
              type="category"
              dataKey="name"
              width={128}
              tick={{
                fill: C.text2,
                fontSize: 10,
              }}
              axisLine={{
                stroke: "#C8D0DA",
              }}
              tickLine={false}
            />

            <Tooltip
              cursor={{
                fill: "#F6F8FA",
              }}
              contentStyle={{
                border: `1px solid ${C.border}`,
                borderRadius: 6,
                fontSize: 11,
              }}
            />

            <Bar
              dataKey="score"
              radius={[0, 3, 3, 0]}
              barSize={25}
            >
              {data.map((entry) => (
                <Cell
                  key={entry.name}
                  fill={entry.fill}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

/* =========================================================
   SALARY FORECAST
   ========================================================= */

function SalaryForecast({ salaryData }) {
  const salary =
    Number(
      salaryData?.predicted_salary ??
        salaryData?.predicted_salary_lpa ??
        salaryData?.salary ??
        salaryData?.prediction ??
        0
      ) || 0;

  const factors = [
    ["Evidence strength", 82, C.blue],
    ["Skill breadth", 68, C.blue],
    ["Experience", 46, C.amber],
    ["Market alignment", 61, C.blue],
  ];

  return (
    <div
      className="grid2"
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 11,
      }}
    >
      <Card
        style={{
          padding: 20,
          minHeight: 245,
        }}
      >
        <SectionTitle
          title="Predicted salary"
          subtitle="Current profile estimate"
        />

        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: 8,
            marginTop: 22,
          }}
        >
          <span
            style={{
              color: C.blueDark,
              fontFamily:
                "'Space Grotesk', Inter, sans-serif",
              fontWeight: 700,
              fontSize: 38,
            }}
          >
            {salary ? `₹${salary.toFixed(1)}L` : "Not available"}
          </span>

          <span
            style={{
              color: C.muted,
              fontSize: 12,
            }}
          >
            per annum
          </span>
        </div>

        <div style={{ marginTop: 23 }}>
          <div
            style={{
              display: "flex",
              justifyContent:
                "space-between",
              color: C.muted,
              fontSize: 9,
              marginBottom: 9,
            }}
          >
            <span>{salary ? `₹${(salary * 0.88).toFixed(1)}L` : "No estimate"}</span>
            <span>{salary ? `₹${(salary * 1.12).toFixed(1)}L` : "Complete profile"}</span>
          </div>

          <div
            style={{
              height: 2,
              background: C.border,
              position: "relative",
            }}
          >
            <div
              style={{
                position: "absolute",
                left: salary ? "50%" : "0%",
                top: -8,
                width: 3,
                height: 18,
                background: C.blueDark,
                borderRadius: 2,
              }}
            />
          </div>
        </div>

        <div
          style={{
            borderTop: `1px solid ${C.soft}`,
            marginTop: 20,
            paddingTop: 13,
          }}
        >
          <b
            style={{
              color: C.text2,
              fontSize: 10,
            }}
          >
            Confidence: {salaryData?.confidence ? `${salaryData.confidence}%` : "Not available"}
          </b>

          <div
            style={{
              color: C.muted,
              fontSize: 10,
              marginTop: 4,
            }}
          >
            {salary ? "This estimate is based on your saved evidence and the current model." : "Add skills, projects, and experience to generate a personalized estimate."}
          </div>
        </div>
      </Card>

      <Card
        style={{
          padding: 20,
          minHeight: 245,
        }}
      >
        <SectionTitle
          title="What influences the estimate"
          subtitle="Profile factors represented in the current model"
        />

        <div style={{ marginTop: 18 }}>
          {factors.map(([name, value, color]) => (
            <div
              key={name}
              style={{
                display: "grid",
                gridTemplateColumns:
                  "125px 1fr 28px",
                alignItems: "center",
                gap: 12,
                marginBottom: 16,
              }}
            >
              <b
                style={{
                  color: C.text2,
                  fontSize: 11,
                }}
              >
                {name}
              </b>

              <div
                style={{
                  height: 7,
                  background: C.track,
                  borderRadius: 99,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    width: `${value}%`,
                    height: "100%",
                    background: color,
                    borderRadius: 99,
                  }}
                />
              </div>

              <b
                style={{
                  color: C.text2,
                  fontSize: 10,
                  textAlign: "right",
                }}
              >
                {value}
              </b>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

/* =========================================================
   CAREER SIMULATOR
   ========================================================= */

function CareerSimulator({ salaryData }) {
  const [selected, setSelected] = useState(["ml"]);

  const baseline = Number(salaryData?.predicted_salary_lpa ?? salaryData?.predicted_salary ?? 0);
  const projected = useMemo(() => {
    return (
      baseline +
      simulationOptions
        .filter((item) =>
          selected.includes(item.id)
        )
        .reduce(
          (total, item) =>
            total + item.impact,
          0
        )
    );
  }, [baseline, selected]);

  const data = [
    {
      name: "Current",
      salary: baseline,
    },
    {
      name: "Projected",
      salary: Number(projected.toFixed(1)),
    },
  ];

  const toggle = (id) => {
    setSelected((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id]
    );
  };

  return (
    <>
      <div
        className="grid2"
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 11,
        }}
      >
        <Card
          style={{
            padding: 20,
            minHeight: 380,
          }}
        >
          <SectionTitle
            title="Career simulator"
            subtitle="Select profile improvements to model a potential salary change"
          />

          <div style={{ marginTop: 14 }}>
            {simulationOptions.map((item) => (
              <label
                key={item.id}
                style={{
                  display: "grid",
                  gridTemplateColumns:
                    "20px 1fr auto",
                  alignItems: "center",
                  gap: 10,
                  minHeight: 49,
                  borderBottom:
                    `1px solid ${C.soft}`,
                  cursor: "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={selected.includes(
                    item.id
                  )}
                  onChange={() =>
                    toggle(item.id)
                  }
                  style={{
                    width: 17,
                    height: 17,
                    accentColor: C.blueDark,
                  }}
                />

                <span
                  style={{
                    color: C.text2,
                    fontSize: 12,
                  }}
                >
                  {item.label}
                </span>

                <b
                  style={{
                    color: C.green,
                    fontSize: 11,
                  }}
                >
                  +₹{item.impact.toFixed(1)}L
                </b>
              </label>
            ))}
          </div>
        </Card>

        <Card
          style={{
            padding: 20,
            minHeight: 380,
          }}
        >
          <SectionTitle
            title="Projected outcome"
            subtitle="Changes are cumulative"
          />

          <div
            style={{
              border: `1px solid ${C.border}`,
              background: "#F7F9FC",
              borderRadius: 7,
              padding: "17px 18px",
              marginBottom: 17,
            }}
          >
            <div
              style={{
                color: C.muted,
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: ".7px",
              }}
            >
              PROJECTED SALARY
            </div>

            <div
              style={{
                color: C.blueDark,
                fontFamily:
                  "'Space Grotesk', Inter, sans-serif",
                fontWeight: 700,
                fontSize: 31,
                marginTop: 5,
              }}
            >
              ₹{projected.toFixed(1)}L
            </div>

            <div
              style={{
                color: C.muted,
                fontSize: 10,
                marginTop: 3,
              }}
            >
              Current baseline: {baseline ? `₹${baseline.toFixed(1)}L` : "Not available"}
            </div>
          </div>

          <div style={{ height: 210 }}>
            <ResponsiveContainer>
              <BarChart
                data={data}
                margin={{
                  top: 5,
                  right: 4,
                  left: 0,
                  bottom: 8,
                }}
              >
                <CartesianGrid
                  vertical={false}
                  stroke="#E6EAF0"
                />

                <XAxis
                  dataKey="name"
                  tick={{
                    fill: C.muted,
                    fontSize: 10,
                  }}
                  axisLine={{
                    stroke: "#B8C1CC",
                  }}
                />

                <YAxis
                  hide
                  domain={[
                    0,
                    Math.max(17, projected + 1),
                  ]}
                />

                <Tooltip
                  formatter={(value) => [
                    `₹${Number(value).toFixed(1)}L`,
                    "Salary",
                  ]}
                  contentStyle={{
                    border: `1px solid ${C.border}`,
                    borderRadius: 6,
                    fontSize: 11,
                  }}
                />

                <Bar
                  dataKey="salary"
                  radius={[3, 3, 0, 0]}
                  barSize={92}
                >
                  <Cell fill="#AAB8CA" />
                  <Cell fill={C.blue} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <Footer />
    </>
  );
}

/* =========================================================
   CAREER GAP
   ========================================================= */

function CareerGap({
  careerGapData,
  selectedRole,
  setSelectedRole,
  roles = [],
}) {
  const match = Number(
    careerGapData?.match ??
      careerGapData?.match_percent ??
      careerGapData?.score ??
      0
  );

  const missing =
    careerGapData?.missing ||
    careerGapData?.missing_skills ||
    careerGapData?.gaps ||
    [];
  const missingNames = missing.map((item) => typeof item === "string" ? item : item.name).filter(Boolean);

  return (
    <>
      <Card style={{ padding: 20 }}>
        <SectionTitle
          title="Career gap analysis"
          subtitle="Compare the current profile with target-role requirements"
          right={
            <select
              value={selectedRole}
              onChange={(event) =>
                setSelectedRole(
                  event.target.value
                )
              }
              style={{
                border: `1px solid ${C.border}`,
                borderRadius: 6,
                background: "#fff",
                color: C.text2,
                padding: "8px 11px",
                fontSize: 11,
              }}
            >
              {roles.map(
                (role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                )
              )}
            </select>
          }
        />

        <div
          className="grid2"
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 28,
            alignItems: "center",
            paddingTop: 10,
          }}
        >
          <div>
            <div
              style={{
                color: C.muted,
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: ".7px",
                marginBottom: 10,
              }}
            >
              ROLE MATCH
            </div>

            <div
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 8,
              }}
            >
              <span
                style={{
                  color: C.text,
                  fontFamily:
                    "'Space Grotesk', Inter, sans-serif",
                  fontWeight: 700,
                  fontSize: 40,
                }}
              >
                {match}%
              </span>

              <span
                style={{
                  color: C.muted,
                  fontSize: 11,
                }}
              >
                profile alignment
              </span>
            </div>

            <div
              style={{
                height: 10,
                background: C.track,
                borderRadius: 99,
                marginTop: 17,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${match}%`,
                  height: "100%",
                  background:
                    missing.length ? C.amber : C.green,
                }}
              />
            </div>
          </div>

          <div>
            <div
              style={{
                color: C.muted,
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: ".7px",
                marginBottom: 10,
              }}
            >
              PRIORITY GAPS
            </div>

            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: 8,
              }}
            >
              {missingNames.map((item) => (
                <Badge
                  key={item}
                  text={item}
                  tone="red"
                />
              ))}
            </div>

            <p
              style={{
                color: C.muted,
                fontSize: 10,
                lineHeight: 1.55,
                margin: "13px 0 0",
              }}
            >
              Closing these gaps would improve
              alignment with the selected target
              role.
            </p>
          </div>
        </div>
      </Card>

      <div
        className="grid3"
        style={{
          display: "grid",
          gridTemplateColumns:
            "1fr 1fr 1fr",
          gap: 11,
          marginTop: 11,
        }}
      >
        <GapCard
          title="Strong evidence"
          items={careerGapData?.strong_skills || []}
        />

        <GapCard
          title="Build next"
          items={missingNames}
          tone="amber"
        />

        <GapCard
          title="Already demonstrated"
          items={careerGapData?.matched_skills || []}
          tone="green"
        />
      </div>

      <Footer />
    </>
  );
}

function GapCard({
  title,
  items,
  tone = "blue",
}) {
  const dot = {
    blue: C.blue,
    amber: C.amber,
    green: C.green,
  }[tone] || C.blue;

  return (
    <Card style={{ padding: 17 }}>
      <b
        style={{
          color: C.text,
          fontSize: 12,
        }}
      >
        {title}
      </b>

      {items.map((item) => (
        <div
          key={item}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "9px 0",
            borderTop: `1px solid ${C.soft}`,
            marginTop: 7,
            color: C.text2,
            fontSize: 10.5,
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: dot,
            }}
          />

          {item}
        </div>
      ))}
    </Card>
  );
}

/* =========================================================
   TIME MACHINE
   ========================================================= */

function TimeMachine({ historyData }) {
  const history =
    Array.isArray(historyData) &&
    historyData.length
      ? historyData
      : defaultHistory;

  if (!history.length) {
    return <Card style={{ padding: 20 }}><SectionTitle title="Career Time Machine" subtitle="Longitudinal view of your profile development and salary potential" /><EmptyState text="Your timeline will appear after salary predictions are recorded for your profile." /></Card>;
  }

  return (
    <>
      <Card style={{ padding: 20 }}>
        <SectionTitle
          title="Career Time Machine"
          subtitle="Longitudinal view of profile development and salary potential"
        />

        <div
          className="grid4"
          style={{
            display: "grid",
            gridTemplateColumns:
              "repeat(4, 1fr)",
            gap: 9,
            marginBottom: 20,
          }}
        >
          {history.slice(-4).map((item, index) => (
            <StatCard
              key={`${item.month}-${index}`}
              label={item.month || "Snapshot"}
              value={`₹${Number(item.salary).toFixed(1)}L`}
              sub={index === history.slice(-4).length - 1 ? "Current snapshot" : "Saved prediction"}
              valueColor={index === history.slice(-4).length - 1 ? C.blue : C.text}
            />
          ))}
        </div>

        <div style={{ height: 330 }}>
          <ResponsiveContainer>
            <LineChart
              data={history}
              margin={{
                top: 10,
                right: 18,
                left: 5,
                bottom: 10,
              }}
            >
              <CartesianGrid
                stroke="#E6EAF0"
                vertical={false}
              />

              <XAxis
                dataKey="month"
                tick={{
                  fill: C.muted,
                  fontSize: 10,
                }}
                axisLine={{
                  stroke: "#C5CDD7",
                }}
                tickLine={false}
              />

              <YAxis
                domain={[8, 16]}
                tick={{
                  fill: C.muted,
                  fontSize: 10,
                }}
                axisLine={{
                  stroke: "#C5CDD7",
                }}
                tickLine={false}
                tickFormatter={(value) =>
                  `₹${value}L`
                }
              />

              <Tooltip
                formatter={(value) => [
                  `₹${Number(value).toFixed(1)}L`,
                  "Estimated salary",
                ]}
                contentStyle={{
                  border: `1px solid ${C.border}`,
                  borderRadius: 6,
                  fontSize: 11,
                }}
              />

              <Line
                type="monotone"
                dataKey="salary"
                stroke={C.blue}
                strokeWidth={3}
                dot={{
                  r: 4,
                  fill: C.blue,
                  stroke: "#fff",
                  strokeWidth: 2,
                }}
                activeDot={{
                  r: 6,
                }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <div
        className="grid2"
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 11,
          marginTop: 11,
        }}
      >
        <Card style={{ padding: 17 }}>
          <SectionTitle
            title="What changed"
            subtitle="Evidence events contributing to the profile"
          />

          <EmptyState text="Evidence events will appear as your profile is updated." />
        </Card>

        <Card style={{ padding: 17 }}>
          <SectionTitle
            title="Next likely inflection"
            subtitle="Highest-impact profile improvement"
          />

          <div
            style={{
              background: C.blueSoft,
              border: "1px solid #DCE6F1",
              borderRadius: 7,
              padding: 15,
            }}
          >
            <b
              style={{
                color: C.blueDark,
                fontSize: 13,
              }}
            >
              Keep building evidence-backed experience
            </b>

            <div
              style={{
                color: C.text2,
                fontSize: 10,
                lineHeight: 1.55,
                marginTop: 7,
              }}
            >
              Add projects, skills, certifications, and roles to make your next recommendation more precise.
            </div>
          </div>
        </Card>
      </div>

      <Footer />
    </>
  );
}

function Timeline({
  date,
  title,
  text,
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns:
          "76px 12px 1fr",
        gap: 10,
        minHeight: 64,
      }}
    >
      <div
        style={{
          color: C.muted,
          fontSize: 9,
        }}
      >
        {date}
      </div>

      <div
        style={{
          position: "relative",
        }}
      >
        <span
          style={{
            position: "absolute",
            top: 3,
            left: 1,
            width: 8,
            height: 8,
            background: C.blue,
            borderRadius: "50%",
          }}
        />

        <span
          style={{
            position: "absolute",
            top: 13,
            left: 4,
            bottom: -8,
            width: 1,
            background: C.border,
          }}
        />
      </div>

      <div>
        <b
          style={{
            color: C.text,
            fontSize: 11,
          }}
        >
          {title}
        </b>

        <div
          style={{
            color: C.muted,
            fontSize: 9.5,
            lineHeight: 1.5,
            marginTop: 4,
          }}
        >
          {text}
        </div>
      </div>
    </div>
  );
}

/* =========================================================
   FOOTER
   ========================================================= */

function Footer() {
  return (
    <div
      style={{
        color: C.muted,
        fontSize: 10,
        marginTop: 22,
        paddingBottom: 4,
      }}
    >
      CareerDNA is a decision-support dashboard.
      Salary figures are estimates, not guaranteed
      compensation.
    </div>
  );
}

/* =========================================================
   MAIN COMPONENT
   ========================================================= */

export default function CareerDNALight({
  user,
  onSignOut,
  onEditProfile,
}) {
  const [active, setActive] =
    useState("Overview");

  const [profile, setProfile] =
    useState(null);

  const [skillsData, setSkillsData] =
    useState([]);

  const [salaryData, setSalaryData] =
    useState(null);

  const [careerGapData, setCareerGapData] =
    useState(null);

  const [jobMatchData, setJobMatchData] =
    useState(null);

  const [historyData, setHistoryData] =
    useState([]);

  const [loading, setLoading] =
    useState(true);

  const [error, setError] =
    useState("");

  const [selectedRole, setSelectedRole] =
    useState("");

  const [simulations, setSimulations] =
    useState([]);

  useEffect(() => {
    let mounted = true;

    async function loadDashboard() {
      try {
        setLoading(true);
        setError("");

        const [
          profileResult,
          skillsResult,
          salaryResult,
          gapResult,
          jobsResult,
          historyResult,
        ] = await Promise.all([
          getProfile(),
          getSkills(),
          getSalary(),
          getCareerGap(selectedRole),
          getJobMatch(),
          getCareerHistory(),
        ]);

        if (!mounted) return;

        setProfile(profileResult);

        setSkillsData(
          skillsResult?.skills ||
            skillsResult ||
            []
        );

        setSalaryData(salaryResult);

        setCareerGapData(gapResult);

        setJobMatchData(jobsResult);

        if (!selectedRole && jobsResult?.jobs?.length) {
          setSelectedRole(jobsResult.jobs[0].role);
        }

        setHistoryData(
          historyResult?.history ||
            historyResult ||
            []
        );
      } catch (err) {
        console.error(
          "CareerDNA dashboard error:",
          err
        );

        if (mounted) {
          setError(
            err?.message ||
              "Unable to load dashboard data."
          );
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }

    loadDashboard();

    return () => {
      mounted = false;
    };
  }, [selectedRole]);

  /* =====================================================
     WHAT-IF HANDLER
     ===================================================== */

  const handleWhatIf = async (payload) => {
    try {
      if (typeof runWhatIf !== "function") {
        return null;
      }

      const result =
        await runWhatIf(payload);

      setSimulations((current) => [
        ...current,
        result,
      ]);

      return result;
    } catch (err) {
      console.error(
        "What-if simulation error:",
        err
      );

      return null;
    }
  };

  /* Prevent unused variable warnings in some setups */
  void jobMatchData;
  void simulations;
  void handleWhatIf;

  /* =====================================================
     LOADING STATE
     ===================================================== */

  if (loading) {
    return (
      <div
        style={{
          minHeight: "100vh",
          background: C.page,
          color: C.text,
          fontFamily:
            "Inter, Arial, sans-serif",
        }}
      >
        <div
          style={{
            maxWidth: 1180,
            margin: "0 auto",
            padding: "0 24px",
          }}
        >
          <Header
            user={user}
            onSignOut={onSignOut}
            onEditProfile={onEditProfile}
          />

          <div
            style={{
              minHeight: 500,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: C.muted,
              fontSize: 13,
            }}
          >
            Loading CareerDNA...
          </div>
        </div>
      </div>
    );
  }

  /* =====================================================
     PAGE
     ===================================================== */

  let pageContent;

  switch (active) {
    case "Skills":
      pageContent = (
        <SkillsPage
          skillsData={skillsData}
        />
      );
      break;

    case "Salary Forecast":
      pageContent = (
        <SalaryForecast
          salaryData={salaryData}
        />
      );
      break;

    case "Career Simulator":
      pageContent = (
        <CareerSimulator salaryData={salaryData} />
      );
      break;

    case "Career Gap":
      pageContent = (
        <CareerGap
          careerGapData={careerGapData}
          selectedRole={selectedRole}
          setSelectedRole={setSelectedRole}
          roles={(jobMatchData?.jobs || []).map((job) => job.role)}
        />
      );
      break;

    case "Time Machine":
      pageContent = (
        <TimeMachine
          historyData={historyData}
        />
      );
      break;

    case "AI Assistant":
      pageContent = (
        <AIAssistant
          theme={C}
          roles={(jobMatchData?.jobs || []).map((job) => job.role)}
        />
      );
      break;

    case "Overview":
    default:
      pageContent = (
        <Overview
          profile={profile}
          skillsData={skillsData}
          salaryData={salaryData}
        />
      );
      break;
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        background: C.page,
        color: C.text,
        fontFamily:
          "Inter, Arial, sans-serif",
      }}
    >
      <div
        style={{
          maxWidth: 1180,
          margin: "0 auto",
          padding: "0 24px 32px",
        }}
      >
        <Header
          user={user}
          onSignOut={onSignOut}
          onEditProfile={onEditProfile}
        />

        {/* =============================================
            NAVIGATION
           ============================================= */}

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
            borderBottom:
              `1px solid ${C.border}`,
            overflowX: "auto",
            marginBottom: 18,
          }}
        >
          {NAV.map((item) => {
            const isActive =
              active === item;

            return (
              <button
                key={item}
                onClick={() =>
                  setActive(item)
                }
                style={{
                  border: "none",
                  background: "transparent",
                  color: isActive
                    ? C.blueDark
                    : C.muted,
                  fontSize: 10.5,
                  fontWeight: isActive
                    ? 700
                    : 500,
                  padding:
                    "12px 13px 10px",
                  cursor: "pointer",
                  borderBottom: isActive
                    ? `2px solid ${C.blueDark}`
                    : "2px solid transparent",
                  whiteSpace: "nowrap",
                }}
              >
                {item}
              </button>
            );
          })}
        </div>

        {/* =============================================
            ERROR
           ============================================= */}

        {error && (
          <div
            style={{
              marginBottom: 14,
              padding: "10px 13px",
              background: "#FBEEEE",
              border: "1px solid #F0D0D0",
              color: C.red,
              borderRadius: 7,
              fontSize: 11,
            }}
          >
            {error}
          </div>
        )}

        {/* =============================================
            PAGE TITLE
           ============================================= */}

        <div
          style={{
            marginBottom: 16,
          }}
        >
          <div
            style={{
              color: C.muted,
              fontSize: 9,
              textTransform: "uppercase",
              letterSpacing: ".8px",
              fontWeight: 700,
              marginBottom: 5,
            }}
          >
            CAREERDNA
          </div>

          <h1
            style={{
              margin: 0,
              color: C.text,
              fontFamily:
                "'Space Grotesk', Inter, sans-serif",
              fontSize: 24,
              fontWeight: 700,
            }}
          >
            {active}
          </h1>
        </div>

        {/* =============================================
            CONTENT
           ============================================= */}

        {pageContent}
      </div>
    </div>
  );
}