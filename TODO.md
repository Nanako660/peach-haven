# Roadmap & TODO List

<div align="center">

[English](TODO.md) | [简体中文](TODO.zh-CN.md)

</div>

> **Disclaimer**: This project is a milestone research artifact and proof-of-concept. It is **not committed to long-term maintenance or continuous updates**. The following list documents known protocol boundaries for academic reference.

---

## 🎯 Gameplay Implementation Roadmap

### 1. Battle & Stage Progression
- [ ] **3-Star Stage Evaluation**: Calculate completion conditions and synchronize star ratings to client.
- [ ] **Stage Drop Fulfillment**: Automatically credit player inventory with configured reward items and EXP upon victory.
- [ ] **Battle Settlement Verification**: Validate client-submitted battle simulation packets and damage calculations.

### 2. Gacha & Recruitment
- [ ] **Drop Rate RNG Model**: Implement recruitment algorithms honoring original banner weighting and card rarities.
- [ ] **Pity Counter Persistence**: Persist gacha counters and guarantee progress across sessions.
- [ ] **Summon Currency Deduction**: Atomically deduct recruitment tickets or diamonds with real-time inventory delta synchronization.

### 3. Tutorial & Lineups
- [ ] **Tutorial Formation Flow**: Support forced lineup assignment during first-time player onboarding.
- [ ] **Multi-Team Presets**: Allow switching, customizing, and saving multiple team formation presets (Team 1, Team 2, etc.).

### 4. Operations & Social
- [ ] **Mail System & Announcements**: Support sending in-game mail with attachments via CLI commands.
- [ ] **Check-in & Daily Tasks**: Implement daily check-in rewards and limited-time task claiming.

---

## 🛠️ Technical Reference

- For detailed compatibility analysis, wire framing, and prioritization criteria, see [`docs/todo/server-compatibility-todo.md`](docs/todo/server-compatibility-todo.md).
