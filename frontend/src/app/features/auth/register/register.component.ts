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
  selector: 'app-register',
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
          <mat-card-title>Create an account</mat-card-title>
          <p class="auth-subtitle">Start watching your endpoints in under a minute.</p>
        </mat-card-header>
        <mat-card-content>
          <form [formGroup]="registerForm" (ngSubmit)="onSubmit()">
            <mat-form-field appearance="outline" fullWidth>
              <mat-label>Username</mat-label>
              <input matInput formControlName="username" required>
              <mat-error *ngIf="registerForm.get('username')?.invalid">Username is required</mat-error>
            </mat-form-field>

            <mat-form-field appearance="outline" fullWidth>
              <mat-label>Email</mat-label>
              <input matInput type="email" formControlName="email" required>
              <mat-error *ngIf="registerForm.get('email')?.hasError('required')">Email is required</mat-error>
              <mat-error *ngIf="registerForm.get('email')?.hasError('email')">Invalid email</mat-error>
            </mat-form-field>

            <mat-form-field appearance="outline" fullWidth>
              <mat-label>Password</mat-label>
              <input matInput type="password" formControlName="password" required>
              <mat-error *ngIf="registerForm.get('password')?.invalid">Password is required (min 8 characters)</mat-error>
            </mat-form-field>

            <mat-form-field appearance="outline" fullWidth>
              <mat-label>Confirm Password</mat-label>
              <input matInput type="password" formControlName="confirmPassword" required>
              <mat-error *ngIf="registerForm.hasError('mismatch')">Passwords do not match</mat-error>
            </mat-form-field>

            <button mat-raised-button color="primary" type="submit" [disabled]="registerForm.invalid || isLoading">
              {{ isLoading ? 'Creating account…' : 'Create account' }}
            </button>
            <button mat-button type="button" routerLink="/login">Already have an account? Log in</button>
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
    .auth-card { width: 450px; max-width: 90%; border-radius: 12px; border-top: 3px solid var(--beacon-500); }
    .auth-subtitle { color: rgba(0,0,0,0.6); font-size: 13px; margin: 2px 0 0; }
    form { display: flex; flex-direction: column; gap: 16px; margin-top: 16px; }
  `]
})
export class RegisterComponent {
  private fb = inject(FormBuilder);
  private authService = inject(AuthService);
  private router = inject(Router);
  private snackBar = inject(MatSnackBar);

  registerForm = this.fb.group({
    username: ['', Validators.required],
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(8)]],
    confirmPassword: ['', Validators.required]
  }, { validators: this.passwordMatchValidator });

  isLoading = false;

  passwordMatchValidator(form: any) {
    const password = form.get('password')?.value;
    const confirm = form.get('confirmPassword')?.value;
    return password === confirm ? null : { mismatch: true };
  }

  onSubmit(): void {
    if (this.registerForm.invalid) return;
    this.isLoading = true;
    const { username, email, password } = this.registerForm.value;
    this.authService.register(username!, email!, password!).subscribe({
      next: () => this.router.navigate(['/dashboard']),
      error: (err) => {
        // Surface backend validation in priority order: password > username > email > generic
        const e = err.error || {};
        const msg =
          e.password?.[0] ||
          e.username?.[0] ||
          e.email?.[0] ||
          e.detail ||
          'Registration failed. Please try again.';
        this.snackBar.open(msg, 'Dismiss', { duration: 5000 });
        this.isLoading = false;
      },
      complete: () => (this.isLoading = false),
    });
  }
}
