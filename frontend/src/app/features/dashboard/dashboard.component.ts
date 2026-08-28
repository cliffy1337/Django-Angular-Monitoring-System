import { Component, OnInit, inject, Inject, signal, computed, effect, viewChild, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators, FormGroup } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTableModule } from '@angular/material/table';
import { MatDialog, MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { forkJoin } from 'rxjs';
import { finalize } from 'rxjs/operators';
import { Chart, registerables } from 'chart.js';
import { EndpointService, Endpoint } from '../../core/services/endpoint.service';
import { CheckService, CheckResult } from '../../core/services/check.service';
import { AuthService } from '../../core/services/auth.service';

Chart.register(...registerables);

interface StatusInfo {
  label: string;
  cssClass: string;
}

interface EndpointRow {
  endpoint: Endpoint;
  check: CheckResult | undefined;
  status: StatusInfo;
}

function endpointStatus(check: CheckResult | undefined): StatusInfo {
  if (!check) return { label: 'Pending', cssClass: 'status-pending' };
  return check.is_up
    ? { label: 'Up',   cssClass: 'status-up'   }
    : { label: 'Down', cssClass: 'status-down' };
}

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    CommonModule, ReactiveFormsModule,
    MatCardModule, MatButtonModule, MatIconModule, MatTableModule, MatDialogModule,
    MatFormFieldModule, MatInputModule, MatSlideToggleModule, MatSnackBarModule,
    MatProgressBarModule,
  ],
  template: `
    <header class="topbar">
      <div class="wordmark">
        <span class="beacon-mark" aria-hidden="true"></span>
        <span class="wordmark-text">VIGIL</span>
      </div>
      <div class="header-actions">
        <button mat-raised-button color="primary" (click)="openEndpointForm()">+ Add Endpoint</button>
        <button mat-stroked-button class="logout-btn" (click)="logout()">Logout</button>
      </div>
    </header>

    <div class="dashboard">
      @if (loading()) {
        <mat-progress-bar mode="indeterminate" aria-label="Loading dashboard data"></mat-progress-bar>
      }

      @if (!loading()) {
        <div class="summary" role="region" aria-label="Summary">
          <mat-card class="stat-card stat-total">
            <mat-card-content>
              <div class="stat-label">Total endpoints</div>
              <div class="big-number">{{ rows().length }}</div>
            </mat-card-content>
          </mat-card>
          <mat-card class="stat-card stat-up">
            <mat-card-content>
              <div class="stat-label">Up now</div>
              <div class="big-number">{{ upCount() }}</div>
            </mat-card-content>
          </mat-card>
          <mat-card class="stat-card stat-down">
            <mat-card-content>
              <div class="stat-label">Down now</div>
              <div class="big-number">{{ downCount() }}</div>
            </mat-card-content>
          </mat-card>
        </div>
      }

      @if (!loading() && rows().length === 0) {
        <mat-card class="empty-state">
          <mat-card-content>
            <mat-icon class="empty-icon" aria-hidden="true">monitor_heart</mat-icon>
            <h2>No endpoints yet</h2>
            <p>Add an endpoint to start monitoring uptime.</p>
            <button mat-raised-button color="primary" (click)="openEndpointForm()">
              Add your first endpoint
            </button>
          </mat-card-content>
        </mat-card>
      }

      @if (!loading() && checks().length > 0) {
        <mat-card>
          <mat-card-title>Response Time (last 20 checks)</mat-card-title>
          <div class="chart-container">
            <canvas #responseChartRef aria-label="Response time chart" role="img"></canvas>
          </div>
        </mat-card>
      }

      @if (!loading() && rows().length > 0) {
        <mat-card>
          <mat-card-title>Endpoints</mat-card-title>
          <table mat-table [dataSource]="rows()" class="mat-elevation-z0" aria-label="Monitored endpoints">

            <ng-container matColumnDef="name">
              <th mat-header-cell *matHeaderCellDef>Name</th>
              <td mat-cell *matCellDef="let row">{{ row.endpoint.name }}</td>
            </ng-container>

            <ng-container matColumnDef="url">
              <th mat-header-cell *matHeaderCellDef>URL</th>
              <td mat-cell *matCellDef="let row" class="url-cell">{{ row.endpoint.url }}</td>
            </ng-container>

            <ng-container matColumnDef="status">
              <th mat-header-cell *matHeaderCellDef>Status</th>
              <td mat-cell *matCellDef="let row">
                <span [ngClass]="row.status.cssClass" class="status-badge">
                  <span class="beacon-dot" aria-hidden="true"></span>
                  {{ row.status.label }}
                </span>
              </td>
            </ng-container>

            <ng-container matColumnDef="actions">
              <th mat-header-cell *matHeaderCellDef>Actions</th>
              <td mat-cell *matCellDef="let row">
                <button mat-icon-button
                        [attr.aria-label]="'Trigger check for ' + row.endpoint.name"
                        (click)="checkNow(row.endpoint.id)">
                  <mat-icon>refresh</mat-icon>
                </button>
                <button mat-icon-button
                        [attr.aria-label]="'Edit ' + row.endpoint.name"
                        (click)="openEndpointForm(row.endpoint)">
                  <mat-icon>edit</mat-icon>
                </button>
                <button mat-icon-button color="warn"
                        [attr.aria-label]="'Delete ' + row.endpoint.name"
                        (click)="deleteEndpoint(row.endpoint.id)">
                  <mat-icon>delete</mat-icon>
                </button>
              </td>
            </ng-container>

            <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
            <tr mat-row *matRowDef="let row; columns: displayedColumns;"></tr>
          </table>
        </mat-card>
      }
    </div>
  `,
  styles: [`
    .topbar {
      display: flex; justify-content: space-between; align-items: center;
      padding: 16px 24px; background: var(--navy-800);
    }
    .wordmark { display: flex; align-items: center; gap: 8px; }
    .beacon-mark {
      width: 10px; height: 10px; border-radius: 50%;
      background: var(--beacon-500);
      box-shadow: 0 0 0 4px rgba(245, 165, 36, 0.18);
    }
    .wordmark-text {
      font-family: var(--font-display); font-weight: 700; font-size: 18px;
      letter-spacing: 0.14em; color: #fff;
    }
    .header-actions { display: flex; gap: 8px; align-items: center; }
    .logout-btn { color: rgba(255,255,255,0.85); border-color: rgba(255,255,255,0.3); }

    .dashboard { padding: 24px; max-width: 1200px; margin: 0 auto; }

    .summary { display: flex; gap: 16px; margin-bottom: 24px; }
    .stat-card { flex: 1; border-top: 3px solid var(--paper-200); }
    .stat-total { border-top-color: var(--navy-800); }
    .stat-up    { border-top-color: var(--up-500); }
    .stat-down  { border-top-color: var(--down-500); }
    .stat-label {
      font-family: var(--font-body);
      font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
      text-transform: uppercase; color: rgba(0,0,0,0.54);
    }
    .big-number {
      font-family: var(--font-mono); font-size: 40px; font-weight: 500;
      line-height: 1.2; margin-top: 4px; color: var(--ink-950);
    }

    mat-card { margin-bottom: 24px; }
    .chart-container { position: relative; height: 280px; padding: 16px 8px 8px; }
    table { width: 100%; }
    .url-cell { font-family: var(--font-mono); font-size: 13px; color: rgba(0,0,0,0.7); }

    .status-badge {
      display: inline-flex; align-items: center; gap: 8px;
      font-weight: 500; font-size: 14px;
    }

    .beacon-dot { position: relative; width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
    .beacon-dot::after {
      content: ''; position: absolute; inset: -5px; border-radius: 50%;
      border: 1.5px solid currentColor; opacity: 0;
    }

    .status-up   { color: var(--up-500); }
    .status-up .beacon-dot { background: var(--up-500); }
    .status-up .beacon-dot::after { animation: beacon-pulse 2.2s ease-out infinite; }

    .status-down .beacon-dot { background: var(--down-500); }
    .status-down { color: var(--down-500); }

    .status-pending { color: var(--pending-500); }
    .status-pending .beacon-dot { background: var(--pending-500); animation: beacon-fade 2.2s ease-in-out infinite; }

    @keyframes beacon-pulse {
      0%   { transform: scale(0.6); opacity: 0.55; }
      100% { transform: scale(1.6); opacity: 0; }
    }
    @keyframes beacon-fade {
      0%, 100% { opacity: 0.35; }
      50%      { opacity: 1; }
    }
    @media (prefers-reduced-motion: reduce) {
      .beacon-dot::after { animation: none !important; }
      .status-pending .beacon-dot { animation: none !important; }
    }

    .empty-state { text-align: center; padding: 48px 24px; }
    .empty-icon {
      font-size: 56px; width: 56px; height: 56px;
      color: var(--paper-200); display: block; margin: 0 auto 16px;
    }
    .empty-state h2 { margin: 0 0 8px; font-weight: 600; }
    .empty-state p  { color: rgba(0,0,0,0.54); margin: 0 0 24px; }
  `],
})
export class DashboardComponent implements OnInit {
  private endpointService = inject(EndpointService);
  private checkService    = inject(CheckService);
  private authService     = inject(AuthService);
  private dialog          = inject(MatDialog);
  private snackBar        = inject(MatSnackBar);

  endpoints = signal<Endpoint[]>([]);
  checks    = signal<CheckResult[]>([]);
  loading   = signal(true);

  displayedColumns = ['name', 'url', 'status', 'actions'];
  chart: Chart | null = null;
  chartCanvas = viewChild<ElementRef<HTMLCanvasElement>>('responseChartRef');

  private checkMap = computed(() => {
    const map = new Map<string, CheckResult>();
    for (const c of this.checks()) {
      if (!map.has(c.endpoint)) map.set(c.endpoint, c);
    }
    return map;
  });

  rows = computed<EndpointRow[]>(() =>
    this.endpoints().map(e => {
      const check = this.checkMap().get(e.id);
      return { endpoint: e, check, status: endpointStatus(check) };
    })
  );

  upCount   = computed(() => this.rows().filter(r => r.check?.is_up === true).length);
  downCount = computed(() => this.rows().filter(r => r.check?.is_up === false).length);

  constructor() {
    effect(() => { this.updateChart(); });
  }

  ngOnInit() {
    this.loadData();
  }

  loadData() {
    this.loading.set(true);
    forkJoin({
      endpoints: this.endpointService.list(),
      checks:    this.checkService.list(),
    }).pipe(
      finalize(() => this.loading.set(false)),
    ).subscribe({
      next: ({ endpoints, checks }) => {
        this.endpoints.set(endpoints);
        this.checks.set(checks);
      },
      error: () => this.snackBar.open('Failed to load data', 'Close', { duration: 3000 }),
    });
  }

  updateChart() {
    const latestChecks = this.checks().slice(0, 20).reverse();
    // Read the canvas via a signal-based viewChild, not document.getElementById:
    // the <canvas> only exists once the @if(checks().length > 0) block has
    // rendered it, and there's no guarantee that's happened yet the moment
    // this effect fires on a checks() change. viewChild() is itself a signal,
    // so once the canvas mounts, this effect re-runs and picks it up —
    // document.getElementById would just silently find nothing and never retry.
    const canvasRef = this.chartCanvas();
    if (this.chart) { this.chart.destroy(); this.chart = null; }
    if (canvasRef && latestChecks.length > 0) {
      this.chart = new Chart(canvasRef.nativeElement, {
        type: 'line',
        data: {
          labels: latestChecks.map(c => new Date(c.checked_at).toLocaleTimeString()),
          datasets: [{
            label: 'Response time (ms)',
            data: latestChecks.map(c => c.response_time_ms),
            borderColor: '#db8b0c',
            fill: false,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
        },
      });
    }
  }

  openEndpointForm(endpoint?: Endpoint) {
    const dialogRef = this.dialog.open(EndpointFormDialog, {
      data: endpoint ?? { name: '', url: '', interval_minutes: 5, is_active: true },
    });

    dialogRef.afterClosed().subscribe(result => {
      if (!result) return;
      let url = result.url.trim();
      if (!url.startsWith('http://') && !url.startsWith('https://')) url = 'https://' + url;
      const payload = { ...result, url, interval_minutes: Number(result.interval_minutes) };

      if (endpoint?.id) {
        this.endpointService.update(endpoint.id, payload).subscribe({
          next: () => { this.snackBar.open('Endpoint updated', 'Close', { duration: 2000 }); this.loadData(); },
          error: () => this.snackBar.open('Update failed', 'Close', { duration: 3000 }),
        });
      } else {
        this.endpointService.create(payload).subscribe({
          next: () => { this.snackBar.open('Endpoint created', 'Close', { duration: 2000 }); this.loadData(); },
          error: () => this.snackBar.open('Creation failed', 'Close', { duration: 3000 }),
        });
      }
    });
  }

  checkNow(id: string) {
    this.endpointService.checkNow(id).subscribe({
      next: () => {
        this.snackBar.open('Check queued', 'Close', { duration: 2000 });
        setTimeout(() => this.loadData(), 2000);
      },
      error: () => this.snackBar.open('Failed to trigger check', 'Close', { duration: 3000 }),
    });
  }

  deleteEndpoint(id: string) {
    if (confirm('Delete this endpoint?')) {
      this.endpointService.delete(id).subscribe({
        next: () => this.loadData(),
        error: () => this.snackBar.open('Delete failed', 'Close', { duration: 3000 }),
      });
    }
  }

  logout() {
    this.authService.logout();
  }
}

// ---------------------------------------------------------------------------
// Endpoint form dialog (unchanged)
// ---------------------------------------------------------------------------

@Component({
  selector: 'endpoint-form-dialog',
  standalone: true,
  imports: [
    CommonModule, ReactiveFormsModule, MatDialogModule,
    MatFormFieldModule, MatInputModule, MatButtonModule, MatSlideToggleModule,
  ],
  template: `
    <h2 mat-dialog-title>{{ data.id ? 'Edit' : 'Add' }} Endpoint</h2>
    <form [formGroup]="form" (ngSubmit)="save()">
      <mat-dialog-content>
        <mat-form-field fullWidth>
          <mat-label>Name</mat-label>
          <input matInput formControlName="name" required>
        </mat-form-field>
        <mat-form-field fullWidth>
          <mat-label>URL</mat-label>
          <input matInput formControlName="url" placeholder="https://example.com" required>
          <mat-hint>Must include http:// or https://</mat-hint>
          <mat-error *ngIf="form.get('url')?.hasError('pattern')">
            Please enter a valid URL (e.g., https://google.com)
          </mat-error>
        </mat-form-field>
        <mat-form-field fullWidth>
          <mat-label>Interval (minutes)</mat-label>
          <input matInput type="number" formControlName="interval_minutes">
        </mat-form-field>
        <mat-slide-toggle formControlName="is_active">Active</mat-slide-toggle>
      </mat-dialog-content>
      <mat-dialog-actions align="end">
        <button mat-button type="button" (click)="dialogRef.close()">Cancel</button>
        <button mat-raised-button color="primary" type="submit" [disabled]="form.invalid">Save</button>
      </mat-dialog-actions>
    </form>
  `,
  styles: [`
    mat-form-field { width: 100%; margin-bottom: 16px; }
    mat-slide-toggle { margin: 16px 0; display: block; }
  `],
})
export class EndpointFormDialog {
  form: FormGroup;

  constructor(
    private fb: FormBuilder,
    public dialogRef: MatDialogRef<EndpointFormDialog>,
    @Inject(MAT_DIALOG_DATA) public data: any,
  ) {
    this.form = this.fb.group({
      name:             [data?.name             ?? '',    Validators.required],
      url:              [data?.url              ?? '',    [Validators.required, Validators.pattern('^https?://.+')]],
      interval_minutes: [data?.interval_minutes ?? 5,    [Validators.required, Validators.min(1)]],
      is_active:        [data?.is_active        ?? true],
    });
  }

  save() {
    if (this.form.valid) this.dialogRef.close(this.form.value);
  }
}
