import { Component, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';
import { CommonModule } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterLink,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatProgressSpinnerModule,
    MatSnackBarModule,
  ],
  template: `
    <div class="auth-shell">
      <div class="wordmark">
        <span class="beacon-mark" aria-hidden="true"></span>
        <span class="wordmark-text">VIGIL</span>
      </div>

      <mat-card class="auth-card">
        <mat-card-header>
          <mat-card-title>Welcome back</mat-card-title>
          <p class="auth-subtitle">Log in to keep watch over your endpoints.</p>
        </mat-card-header>
        <mat-card-content>
          <form [formGroup]="loginForm" (ngSubmit)="onSubmit()">
            <mat-form-field appearance="outline" fullWidth>
              <mat-label>Username</mat-label>
              <input matInput formControlName="username" required>
              <mat-error *ngIf="loginForm.get('username')?.invalid">Username is required</mat-error>
            </mat-form-field>

            <mat-form-field appearance="outline" fullWidth>
              <mat-label>Password</mat-label>
              <input matInput type="password" formControlName="password" required>
              <mat-error *ngIf="loginForm.get('password')?.invalid">Password is required</mat-error>
            </mat-form-field>

            <button mat-raised-button color="primary" type="submit" [disabled]="loginForm.invalid || isLoading">
              {{ isLoading ? 'Logging in…' : 'Log in' }}
            </button>
            <button mat-button type="button" routerLink="/register">Don't have an account? Register</button>
          </form>
        </mat-card-content>
      </mat-card>
    </div>
  `,
  styles: [`
    .auth-shell {
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      gap: 32px; min-height: 100vh; padding: 24px;
      background:
        radial-gradient(ellipse 700px 420px at 50% 8%, rgba(245, 165, 36, 0.16), transparent 70%),
        var(--navy-800);
    }
    .wordmark { display: flex; align-items: center; gap: 10px; }
    .beacon-mark {
      width: 12px; height: 12px; border-radius: 50%;
      background: var(--beacon-500);
      box-shadow: 0 0 0 5px rgba(245, 165, 36, 0.18);
    }
    .wordmark-text {
      font-family: var(--font-display); font-weight: 700; font-size: 22px;
      letter-spacing: 0.14em; color: #fff;
    }
    .auth-card { width: 400px; max-width: 90%; border-radius: 12px; border-top: 3px solid var(--beacon-500); }
    .auth-subtitle { color: rgba(0,0,0,0.6); font-size: 13px; margin: 2px 0 0; }
    form { display: flex; flex-direction: column; gap: 16px; margin-top: 16px; }
  `]
})
export class LoginComponent {
  private fb = inject(FormBuilder);
  private authService = inject(AuthService);
  private router = inject(Router);
  private snackBar = inject(MatSnackBar);

  loginForm = this.fb.group({
    username: ['', Validators.required],
    password: ['', Validators.required]
  });

  isLoading = false;

  onSubmit(): void {
    if (this.loginForm.invalid) return;
    this.isLoading = true;
    const { username, password } = this.loginForm.value;
    this.authService.login(username!, password!).subscribe({
      next: () => this.router.navigate(['/dashboard']),
      error: (err) => {
        const e = err.error || {};
        const msg = e.detail || e.non_field_errors?.[0] || 'Login failed. Check your credentials.';
        this.snackBar.open(msg, 'Dismiss', { duration: 4000 });
        this.isLoading = false;
      },
      complete: () => (this.isLoading = false),
    });
  }
}
