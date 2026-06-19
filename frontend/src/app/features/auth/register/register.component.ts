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
    <div class="register-container">
      <mat-card>
        <mat-card-header>
          <mat-card-title>Create an Account</mat-card-title>
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
              {{ isLoading ? 'Registering...' : 'Register' }}
            </button>
            <button mat-button type="button" routerLink="/login">Already have an account? Login</button>
          </form>
        </mat-card-content>
      </mat-card>
    </div>
  `,
  styles: [`
    .register-container { display: flex; justify-content: center; align-items: center; height: 100vh; background: #f5f5f5; }
    mat-card { width: 450px; max-width: 90%; }
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
