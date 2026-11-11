# Trello update — ship `9ba84da` (2026-11-11)

Board: https://trello.com/b/DFPaujG8/simust-project-management

**@Siamak (Product Owner) — please review / verify**

## Suggested card titles

### Done
1. Goal area = editable 3D triangle mesh only (calib + live + hit-test)
2. White mesh points/links only (no green solid fill)
3. Field A/B full-screen half view in Goal Area Calibration
4. Entry Players assets (`*-B.png`) + shared still scale
5. Activated Players assets (`*-B.png`) + same size as Entry
6. Realtime video always finalized on Stop / program exit

### Verify (assign / mention **Siamak**)
1. Ball Correct only inside triangle-mesh volume (not goal-line cross)
2. Calibration + live tests show white points + wire only
3. Entry / Activated player stills same on-screen size
4. Mid-test Stop still leaves a playable `realtime_recording.mp4`

## Status
Pushed branch: `simust_development_players_tests_design` (`9ba84da`).  
Promote to `main` when ready (lab VPS pull after main update).

## Summary
- **Goal mesh:** `simust_cylinder_mesh` + WebGL viewer; mesh-only display & `point_inside_mesh` hit-test; classic solid removed.
- **Calibration UI:** Field A or B half full-width; one 3D mesh row; Ctrl-drag vertices.
- **Players:** Entry + Activated PNG set updated; `ACTIVATED_S0_PASS_IMAGE_SCALE = ENTRY_S0_PASS_IMAGE_SCALE` (0.9427); uniform stills preserved in independent compose.
- **Video save:** finalize MP4 before camera kill (Stop, atexit, SIGINT); longer ffmpeg wait.

## Deploy checklist
- [x] GitHub feature branch pushed (`9ba84da`)
- [ ] Merge / push `main` (needs explicit promote)
- [ ] Lab: restart smart player + realtime camera
- [ ] VPS: `sudo bash /opt/simust/deploy/update-vps.sh main` after main update
- [ ] **Siamak:** verify mesh hit-test + white wire on live play
- [ ] **Siamak:** verify Entry/Activated still sizes match

## Notify product owner
Mention **@Siamak** on Done + Verify cards so the board highlights his name.
