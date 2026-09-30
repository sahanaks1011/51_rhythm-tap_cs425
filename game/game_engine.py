import pygame
import random
import array
import math
from game.beat import Note, LANES, LANE_KEYS, LANE_LABELS, LANE_COLORS

WIDTH, HEIGHT = 480, 640
FPS = 60
HIT_Y = HEIGHT - 80
HIT_WINDOW = 30
BG = (15, 10, 25)
LANE_W = WIDTH // LANES

BPM = 120
BEAT_MS = 60000 / BPM      # 500 ms per beat at 120 BPM
HOLD_MS = 1000             # hold notes must be held for 1 second
HOLD_CHANCE = 0.2          # 20% of notes are hold notes
GRADE_COLORS = {
    "PERFECT": (255, 220, 0),
    "GREAT": (100, 220, 100),
    "OK": (180, 180, 255),
    "MISS": (220, 60, 60),
}

class GameEngine:
    def __init__(self):
        pygame.mixer.pre_init(44100, -16, 1, 512)
        pygame.init()
        self.sounds = self.load_sounds()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Rhythm Tap")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("monospace", 26, bold=True)
        self.small_font = pygame.font.SysFont("monospace", 20, bold=True)
        self.big_font = pygame.font.SysFont("monospace", 44, bold=True)
        self.reset()

    def now(self):
        return pygame.time.get_ticks()

    def make_tone(self, freq, ms, volume=0.4):
        # Build a short beep in memory so no audio files are needed
        rate, size, channels = pygame.mixer.get_init()
        n = int(rate * ms / 1000)
        buf = array.array('h')
        for i in range(n):
            fade = 1 - i / n
            v = int(32767 * volume * fade * math.sin(2 * math.pi * freq * i / rate))
            buf.extend([v] * channels)
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def load_sounds(self):
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            return {
                "PERFECT": self.make_tone(880, 90),
                "GREAT": self.make_tone(660, 90),
                "OK": self.make_tone(440, 90),
            }
        except pygame.error:
            return {}  # no audio device, play silently

    def play_sound(self, grade):
        sound = self.sounds.get(grade)
        if sound:
            sound.play()

    def reset(self):
        self.notes = []
        self.score = 0
        self.combo = 0
        self.max_combo = 0
        self.misses = 0
        self.speed = 5
        self.frame = 0
        self.feedback = []  # (text, color, ttl, x, y)
        self.game_over = False
        self.counts = {"PERFECT": 0, "GREAT": 0, "OK": 0}
        self.holding = {}   # lane -> info about the hold note being held
        self.start_time = self.now()
        self.next_beat = 0  # index of the next beat to spawn on
        self.beat_flash = 0

    def spawn_note(self):
        # Only use lanes whose previous note (including a hold tail) has cleared the top
        free = [l for l in range(LANES)
                if all(n.lane != l or n.tail_y() > 40 for n in self.notes if not n.hit)]
        if not free:
            return
        lane = random.choice(free)
        hold = random.random() < HOLD_CHANCE
        self.notes.append(Note(lane, y=-30, speed=self.speed, hold=hold))

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT: return False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_r:
                    self.reset()
                elif not self.game_over:
                    for i, key in enumerate(LANE_KEYS):
                        if event.key == key:
                            self.process_tap(i)
            if event.type == pygame.KEYUP and not self.game_over:
                for i, key in enumerate(LANE_KEYS):
                    if event.key == key:
                        self.process_release(i)
        return True

    def lane_x(self, lane):
        return lane * LANE_W + LANE_W // 2

    def grade_for(self, dist):
        if dist < 8:
            return "PERFECT", 300
        elif dist < 18:
            return "GREAT", 200
        return "OK", 100

    def register_hit(self, grade, pts, lane):
        self.counts[grade] += 1
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        self.score += pts * max(1, self.combo // 5)
        self.feedback.append([grade, GRADE_COLORS[grade], 40, self.lane_x(lane), HIT_Y - 30])
        self.play_sound(grade)

    def register_miss(self, lane=None):
        self.misses += 1
        self.combo = 0
        if lane is not None:
            self.feedback.append(["MISS", GRADE_COLORS["MISS"], 40, self.lane_x(lane), HIT_Y - 30])

    def process_tap(self, lane):
        # Find closest note in this lane near hit zone
        best = None
        best_dist = 9999
        for note in self.notes:
            if note.lane == lane and not note.hit and not note.missed and not note.holding:
                dist = abs(note.y + Note.HEIGHT//2 - HIT_Y)
                if dist < best_dist:
                    best_dist = dist
                    best = note
        if best and best_dist <= HIT_WINDOW:
            grade, pts = self.grade_for(best_dist)
            if best.hold:
                # Start holding; points are only given after 1 second
                best.holding = True
                self.holding[lane] = {"note": best, "grade": grade, "pts": pts, "start": self.now()}
                self.feedback.append(["HOLD", (255,255,255), 30, self.lane_x(lane), HIT_Y - 30])
            else:
                best.hit = True
                self.register_hit(grade, pts, lane)
        else:
            self.combo = 0
            self.feedback.append(["MISS", GRADE_COLORS["MISS"], 40, self.lane_x(lane), HIT_Y - 30])

    def process_release(self, lane):
        # Letting go of a hold note before 1 second counts as a miss
        info = self.holding.pop(lane, None)
        if info:
            info["note"].holding = False
            info["note"].hit = True
            self.register_miss(lane)

    def update(self):
        if self.game_over: return
        self.frame += 1
        if self.frame % 600 == 0:
            self.speed = min(10, self.speed + 0.5)

        # Spawn exactly on each beat of the BPM, using real time
        elapsed = self.now() - self.start_time
        beat = int(elapsed // BEAT_MS)
        if beat >= self.next_beat:
            self.spawn_note()
            self.next_beat = beat + 1
            self.beat_flash = 6
        if self.beat_flash > 0:
            self.beat_flash -= 1

        # Finish hold notes that have been held long enough
        for lane, info in list(self.holding.items()):
            if self.now() - info["start"] >= HOLD_MS:
                info["note"].holding = False
                info["note"].hit = True
                del self.holding[lane]
                self.register_hit(info["grade"], info["pts"] * 2, lane)

        for note in self.notes:
            note.update()
            if not note.hit and not note.missed and not note.holding and note.y + Note.HEIGHT//2 > HIT_Y + HIT_WINDOW:
                note.missed = True
                self.register_miss()

        self.notes = [n for n in self.notes if not (n.hit or n.missed and n.tail_y() > HEIGHT + 10)]
        self.feedback = [[t,c,ttl-1,x,y] for t,c,ttl,x,y in self.feedback if ttl > 1]

        if self.misses >= 15:
            self.game_over = True

    def accuracy(self):
        total = self.counts["PERFECT"] + self.counts["GREAT"] + self.counts["OK"] + self.misses
        if total == 0:
            return 0.0
        earned = 300*self.counts["PERFECT"] + 200*self.counts["GREAT"] + 100*self.counts["OK"]
        return 100 * earned / (300 * total)

    def draw_note(self, note):
        lx = self.lane_x(note.lane)
        color = LANE_COLORS[note.lane]
        if note.missed:
            color = tuple(c // 3 for c in color)
        if note.hold:
            # Tail of the hold note; while held it is cut off at the hit line
            bottom = HIT_Y if note.holding else note.y + Note.HEIGHT
            top = max(note.tail_y(), -50)
            if bottom > top:
                body = pygame.Rect(lx - 14, int(top), 28, int(bottom - top))
                pygame.draw.rect(self.screen, color, body, border_radius=8)
                pygame.draw.rect(self.screen, (255,255,255), body, 2, border_radius=8)
            if note.holding:
                return
        rect = note.get_rect(lx)
        pygame.draw.rect(self.screen, color, rect, border_radius=5)
        if note.hold:
            pygame.draw.rect(self.screen, (255,255,255), rect, 2, border_radius=5)

    def draw(self):
        self.screen.fill(BG)
        # Lane dividers
        for i in range(LANES + 1):
            pygame.draw.line(self.screen, (40,40,60), (i*LANE_W,0), (i*LANE_W,HEIGHT), 1)

        # Hit line, flashes on every beat
        line_col = (200,200,230) if self.beat_flash > 0 else (80,80,100)
        pygame.draw.line(self.screen, line_col, (0,HIT_Y), (WIDTH,HIT_Y), 2)

        # Notes (drawn before the pads so hold tails sit behind them)
        for note in self.notes:
            if note.hit: continue
            self.draw_note(note)

        for i in range(LANES):
            lx = self.lane_x(i)
            pygame.draw.rect(self.screen, LANE_COLORS[i],
                pygame.Rect(lx - Note.WIDTH//2, HIT_Y - 12, Note.WIDTH, 24), border_radius=6)
            lbl = self.font.render(LANE_LABELS[i], True, (20,20,20))
            self.screen.blit(lbl, (lx - lbl.get_width()//2, HIT_Y - 10))

        # Hold progress bars under the pads
        for lane, info in self.holding.items():
            progress = min(1, (self.now() - info["start"]) / HOLD_MS)
            lx = self.lane_x(lane)
            pygame.draw.rect(self.screen, (60,60,80), pygame.Rect(lx - 35, HIT_Y + 20, 70, 8))
            pygame.draw.rect(self.screen, (255,255,255), pygame.Rect(lx - 35, HIT_Y + 20, int(70 * progress), 8))

        # Feedback
        for text, color, ttl, x, y in self.feedback:
            surf = self.font.render(text, True, color)
            alpha = min(255, ttl * 7)
            surf.set_alpha(alpha)
            self.screen.blit(surf, (x - surf.get_width()//2, y))

        # HUD
        sc = self.font.render(f"Score: {self.score}", True, (220,220,220))
        co = self.font.render(f"Combo: {self.combo}x", True, (255,220,80))
        mi = self.font.render(f"Misses: {self.misses}/15", True, (220,100,100))
        bpm = self.small_font.render(f"{BPM} BPM", True, (160,160,200))
        self.screen.blit(sc, (10, 10))
        self.screen.blit(co, (10, 40))
        self.screen.blit(mi, (WIDTH - mi.get_width() - 10, 10))
        self.screen.blit(bpm, (WIDTH - bpm.get_width() - 10, 44))

        if self.game_over:
            self.draw_summary()
        pygame.display.flip()

    def draw_summary(self):
        ov = pygame.Surface((WIDTH,HEIGHT), pygame.SRCALPHA)
        ov.fill((0,0,0,200))
        self.screen.blit(ov,(0,0))

        def center(surf, y):
            self.screen.blit(surf, (WIDTH//2 - surf.get_width()//2, y))

        center(self.big_font.render("GAME OVER", True, (220,60,60)), 90)
        center(self.font.render(f"Final Score: {self.score}", True, (200,200,200)), 160)
        center(self.font.render(f"Max Combo: {self.max_combo}x", True, (200,200,200)), 195)

        rows = [("PERFECT", self.counts["PERFECT"]), ("GREAT", self.counts["GREAT"]),
                ("OK", self.counts["OK"]), ("MISS", self.misses)]
        y = 260
        for name, count in rows:
            center(self.font.render(f"{name:<8}{count:>4}", True, GRADE_COLORS[name]), y)
            y += 35
        center(self.font.render(f"Accuracy: {self.accuracy():.1f}%", True, (255,255,255)), y + 15)
        center(self.font.render("Press R to Restart", True, (160,160,160)), y + 80)

    def run(self):
        running = True
        while running:
            running = self.handle_events()
            self.update()
            self.draw()
            self.clock.tick(FPS)
        pygame.quit()